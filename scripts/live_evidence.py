"""Run against real services; export tool responses and two recovered failure drills."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.orchestrator import Orchestrator
from agent.schemas import ChatRequest, ToolArgs
from agent.tools.airflow_tools import AirflowTools

ROOT = Path("evidence/live")
ROOT.mkdir(parents=True, exist_ok=True)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def save(name, data):
    (ROOT / f"{name}.json").write_text(json.dumps(data, indent=2, default=str) + "\n")


def conversation(name, message, arguments=None, confirmation=None):
    request = ChatRequest(message=message, arguments=arguments or ToolArgs(), confirmation=confirmation)
    response = engine.chat(request)
    save(name, {"request": request.model_dump(), "response": response.model_dump()})
    failures = [e for e in response.evidence if e.status != "ok"]
    assert not failures, [(e.tool, e.error) for e in failures]
    return response


def wait_run(run_id, expected="success"):
    for _ in range(120):
        state = airflow.request("GET", f"/dags/training_pipeline/dagRuns/{run_id}")
        if state["state"] in {"success", "failed"}:
            assert state["state"] == expected, state
            return {"run": state, "tasks": airflow.tasks(ToolArgs(run_id=run_id))}
        time.sleep(5)
    raise TimeoutError(f"Airflow run did not finish: {run_id}")


password_file = command("docker", "compose", "exec", "-T", "airflow", "cat", "/opt/airflow/passwords.json")
os.environ["AIRFLOW_PASSWORD"] = json.loads(password_file)["admin"]
settings = Settings(_env_file=None)
engine = Orchestrator(settings)
airflow = AirflowTools(settings)
for _ in range(60):
    try:
        dags = airflow.dags(ToolArgs())
        if any(d["dag_id"] == "training_pipeline" for d in dags["dags"]):
            break
    except Exception:
        pass
    time.sleep(5)
else:
    raise RuntimeError("Training DAG was not loaded")
airflow.request("PATCH", "/dags/training_pipeline", json={"is_paused": False})

save("execution", {"captured_at": datetime.now(timezone.utc).isoformat(),
                   "git_commit": command("git", "rev-parse", "HEAD"),
                   "environment": "GitHub Actions / Docker Compose / kind", "mocked": False})
conversation("01-dataset-provenance", "Identify the current dataset version and reproduce it")
conversation("02-model-selection", "Find the best recent model based on f1")
trigger = conversation("03-pipeline-request", "Trigger the training pipeline",
                       confirmation="CONFIRM airflow.trigger training_pipeline")
run_id = trigger.evidence[0].data["dag_run_id"]
save("03-pipeline-completion", wait_run(run_id))
conversation("03-pipeline-status", "Check training pipeline status")
conversation("04-deployment-diagnosis", "Check Kubernetes deployment health")
conversation("05-multi-tool-assessment", "Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary")

# Demonstrate retrieval from a DVC remote into a separate, detached worktree.
with tempfile.TemporaryDirectory() as temp:
    remote, checkout = str(Path(temp) / "remote"), str(Path(temp) / "checkout")
    command("dvc", "remote", "add", "--local", "-f", "verification", remote)
    command("dvc", "push", "data/iris.csv.dvc", "-r", "verification")
    command("git", "worktree", "add", "--detach", checkout, "HEAD")
    try:
        subprocess.run(["dvc", "remote", "add", "--local", "-f", "verification", remote], cwd=checkout, check=True)
        subprocess.run(["dvc", "pull", "data/iris.csv.dvc", "-r", "verification"], cwd=checkout, check=True)
        expected = hashlib.md5(Path("data/iris.csv").read_bytes()).hexdigest()
        actual = hashlib.md5(Path(checkout, "data/iris.csv").read_bytes()).hexdigest()
        assert expected == actual
        save("dvc-reproduction", {"source_md5": expected, "restored_md5": actual,
                                  "matched": True, "method": "DVC remote pull in detached Git worktree"})
    finally:
        command("git", "worktree", "remove", "--force", checkout)

# Failure 1: genuine Airflow validation exception, retries and blocked downstream tasks.
failed_id = "validation_failure__" + str(int(time.time()))
airflow.request("POST", "/dags/training_pipeline/dagRuns", json={
    "dag_run_id": failed_id, "logical_date": datetime.now(timezone.utc).isoformat(),
    "conf": {"inject_failure": "validation"},
})
save("failure-01-validation", wait_run(failed_id, "failed"))
conversation("failure-01-agent-diagnosis", "Check training pipeline status")
recovered = airflow.trigger(ToolArgs())
save("failure-01-recovery", wait_run(recovered["dag_run_id"]))

# Failure 2: the service process runs but its configured model directory is absent.
command("kubectl", "set", "env", "deployment/prediction-api", "-n", "mlops", "MODEL_DIR=/missing")
try:
    for _ in range(40):
        pods = engine.registry["kubernetes.pods"](ToolArgs())["pods"]
        if any(not p["ready"] and p["phase"] == "Running" for p in pods):
            time.sleep(15)
            break
        time.sleep(3)
    response = conversation("failure-02-readiness", "Why is my prediction API unavailable?")
    assert any(not p["ready"] for e in response.evidence if e.tool == "kubernetes.pods" for p in e.data["pods"])
finally:
    command("kubectl", "set", "env", "deployment/prediction-api", "-n", "mlops", "MODEL_DIR-")
    command("kubectl", "rollout", "status", "deployment/prediction-api", "-n", "mlops", "--timeout=180s")
conversation("failure-02-recovery", "Check Kubernetes deployment health")

# Probe real serving traffic from inside the cluster through the ClusterIP Service.
pod = engine.registry["kubernetes.pods"](ToolArgs())["pods"][0]["name"]
response = command("kubectl", "exec", "-n", "mlops", pod, "--", "python", "-c",
                   "import urllib.request; print(urllib.request.urlopen('http://prediction-api/health/ready').read().decode())")
save("inference-readiness", json.loads(response))
print("Five live conversations, DVC reproduction and both recovered failure drills exported.")
