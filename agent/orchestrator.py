import json
import logging
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from agent.schemas import ChatResponse, ToolArgs, ToolResult
from agent.tools.airflow_tools import AirflowTools
from agent.tools.dvc_tools import DVCTools
from agent.tools.kubernetes_tools import KubernetesTools
from agent.tools.mlflow_tools import MLflowTools

LOG = logging.getLogger("opspilot.tools")
MUTATIONS = {"airflow.trigger", "kubernetes.restart"}


def redact(value):
    """Scrub secrets from untrusted service logs before returning evidence."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"password|token|secret|api.?key", k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[\w.\-]+", "Bearer [REDACTED]", value)
        return re.sub(r"(?i)((?:password|token|secret|api_key)\s*[=:]\s*)[^\s,;]+",
                      r"\1[REDACTED]", value)
    return value


class Orchestrator:
    def __init__(self, settings, registry=None):
        self.settings = settings
        if registry is not None:
            self.registry = registry
            return
        modules = {"dvc": DVCTools(settings), "mlflow": MLflowTools(settings),
                   "airflow": AirflowTools(settings), "kubernetes": KubernetesTools(settings)}
        methods = {"dvc": ["datasets", "version", "compare", "status", "reproduce"],
                   "mlflow": ["experiments", "runs", "details", "best", "compare", "registry"],
                   "airflow": ["dags", "runs", "trigger", "tasks", "logs"],
                   "kubernetes": ["pods", "deployments", "services", "events", "logs", "restart"]}
        self.registry = {f"{module}.{method}": getattr(modules[module], method)
                         for module, names in methods.items() for method in names}

    def plan(self, message):
        text = message.lower()
        # Mutation selection is never delegated to a language model.
        if re.match(r"^\s*(please\s+)?(trigger|start|run)\s+(the\s+)?(model\s+)?training", text):
            return ["airflow.trigger"]
        if re.match(r"^\s*(please\s+)?restart\s+", text):
            return ["kubernetes.restart"]
        if "best" in text and any(w in text for w in ["deploy", "retrain", "kubernetes"]):
            return ["mlflow.best", "dvc.version", "dvc.status", "kubernetes.deployments",
                    "kubernetes.pods", "kubernetes.services", "kubernetes.events", "airflow.runs"]
        if self.settings.ollama_url:
            allowed = sorted(set(self.registry) - MUTATIONS)
            response = httpx.post(self.settings.ollama_url.rstrip("/") + "/api/chat", json={
                "model": self.settings.llm_model, "stream": False,
                "format": {"type": "object", "properties": {"tools": {"type": "array",
                           "items": {"type": "string", "enum": allowed}, "maxItems": 12}},
                           "required": ["tools"], "additionalProperties": False},
                "messages": [{"role": "system", "content":
                              "Select read-only operations for the user's request. Tools: " +
                              ", ".join(allowed) + ". Never infer or report tool results."},
                             {"role": "user", "content": message}],
            }, timeout=self.settings.tool_timeout)
            response.raise_for_status()
            names = json.loads(response.json()["message"]["content"])["tools"]
            if not isinstance(names, list) or len(names) > 12 or any(n not in allowed for n in names):
                raise ValueError("Planner returned an invalid tool selection")
            return list(dict.fromkeys(names))
        if any(w in text for w in ["unavailable", "unhealthy", "deployment", "pods", "kubernetes"]):
            return ["kubernetes.deployments", "kubernetes.pods", "kubernetes.services", "kubernetes.events"]
        if "dataset" in text or "dvc" in text:
            if "experiment" in text or "run" in text:
                return ["mlflow.details", "dvc.version", "dvc.reproduce"]
            if "compare" in text:
                return ["dvc.compare"]
            return ["dvc.datasets", "dvc.version", "dvc.status", "dvc.reproduce"]
        if any(w in text for w in ["best", "compare", "experiment", "metric", "model"]):
            return ["mlflow.best"] if "best" in text else ["mlflow.runs"]
        if any(w in text for w in ["pipeline", "airflow", "dag", "training"]):
            return ["airflow.dags", "airflow.runs"]
        raise ValueError("Ask about dataset provenance, experiments, training, or deployment health")

    def execute(self, name, args, request_id, confirmation=None):
        started = time.monotonic()
        status, data, error = "ok", None, None
        try:
            if name not in self.registry:
                raise ValueError("Unknown tool")
            if name in MUTATIONS:
                target = (args.dag_id if name == "airflow.trigger" else
                          f"{args.namespace}/{self.settings.kube_deployment}")
                if confirmation != f"CONFIRM {name} {target}":
                    raise PermissionError(f"Explicit confirmation required: CONFIRM {name} {target}")
            if name.startswith("kubernetes.") and args.namespace != self.settings.kube_namespace:
                raise PermissionError("Namespace is not approved")
            if name == "airflow.trigger" and args.dag_id != self.settings.approved_dag:
                raise PermissionError("DAG is not approved")
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                data = pool.submit(self.registry[name], args).result(self.settings.tool_timeout)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            data = redact(data)
        except PermissionError as exc:
            status, error = "denied", str(exc)
        except (TimeoutError, subprocess.TimeoutExpired, httpx.TimeoutException):
            status, error = "timeout", "Tool deadline exceeded; outcome is unknown. Inspect before retrying writes."
        except ValueError as exc:
            status, error = "error", str(exc)
        except Exception as exc:
            # Never expose credentials, server bodies or command stderr from arbitrary exceptions.
            status, error = "error", f"Service operation failed ({type(exc).__name__}); no result available."
        duration = round((time.monotonic() - started) * 1000, 2)
        LOG.info(json.dumps({"tool": name, "status": status, "duration_ms": duration,
                             "request_id": request_id}))
        return ToolResult(tool=name, status=status, data=data, error=error,
                          duration_ms=duration, request_id=request_id)

    def chat(self, request):
        request_id = uuid4().hex
        evidence, facts, unknowns, actions = [], [], [], []
        args = request.arguments.model_copy(deep=True)
        try:
            plan = self.plan(request.message)
            if "compare" in request.message.lower() and args.run_ids and "mlflow.runs" in plan:
                plan = ["mlflow.compare"]
        except Exception as exc:
            return ChatResponse(request_id=request_id, facts=[], evidence=[], recommendations=[],
                                uncertainties=[f"Request planning failed ({type(exc).__name__})."])
        provenance_required = "mlflow.best" in plan or "mlflow.details" in plan
        selected = None
        for name in plan:
            if name in {"dvc.version", "dvc.reproduce"} and provenance_required:
                commit = (selected or {}).get("tags", {}).get("git.commit")
                if not commit:
                    unknowns.append("Selected experiment has no verified Git provenance; dataset lookup skipped.")
                    continue
                args.revision = commit
            result = self.execute(name, args, request_id, request.confirmation)
            evidence.append(result)
            if result.status != "ok":
                unknowns.append(f"{name}: {result.error}")
                continue
            data = result.data
            if name == "mlflow.best":
                selected = data.get("selected")
                if selected:
                    facts.append(f"Best of {data['window']} recent runs by {data['metric']} "
                                 f"({data['direction']}): {selected['run_id']} = "
                                 f"{selected['metrics'][data['metric']]}. This is a candidate, not a release approval.")
                else:
                    unknowns.append("No finished candidate with the requested metric was found.")
            elif name == "mlflow.details":
                selected = data
                facts.append(f"Run {data['run_id']} has recorded parameters, metrics and artifacts.")
            elif name == "dvc.version":
                facts.append(f"Dataset references were read from Git commit {data['git_commit']}.")
                expected = (selected or {}).get("tags", {}).get("dvc.md5")
                hashes = [o.get("md5") for v in data.get("references", {}).values()
                          for o in v.get("outs", [])]
                if expected and expected not in hashes:
                    unknowns.append("Recorded dataset hash does not match the referenced DVC metadata.")
            elif name == "dvc.status" and data.get("changes"):
                facts.append("DVC reports changed workspace dependencies or outputs; see evidence.")
            elif name == "kubernetes.pods":
                pods = data.get("pods", [])
                facts.append(f"Observed {len(pods)} application Pods; {sum(p['ready'] for p in pods)} ready.")
                for pod in pods:
                    if not pod["ready"] or pod["restarts"]:
                        facts.append(f"Pod {pod['name']}: phase={pod['phase']}, restarts={pod['restarts']}.")
                        log_args = args.model_copy(update={"pod": pod["name"]})
                        logs = self.execute("kubernetes.logs", log_args, request_id)
                        evidence.append(logs)
                        if logs.status == "ok" and "Approved model unavailable" in logs.data.get("logs", ""):
                            facts.append(f"Container logs for {pod['name']} report an unavailable approved model.")
                            actions.append("Restore the configured model directory and verify that the approved serving bundle exists.")
                if not pods or not all(p["ready"] for p in pods):
                    actions.append("Investigate Pod events and container logs before restarting the application.")
            elif name == "kubernetes.deployments":
                for deployment in data.get("deployments", []):
                    facts.append(f"Deployment {deployment['name']}: {deployment['ready']}/"
                                 f"{deployment['desired']} ready; image={','.join(deployment['images'])}.")
                    deployed = deployment["annotations"].get("opspilot/model-run-id")
                    if selected and deployed != selected["run_id"]:
                        unknowns.append("Deployment does not identify the selected run as its serving model.")
            elif name == "kubernetes.events":
                events = [e for e in data.get("events", [])
                          if self.settings.kube_deployment in (e.get("object") or "")]
                for event in events[-5:]:
                    facts.append(f"Kubernetes event {event['reason']} on {event['object']}: {event['message']}")
            elif name == "airflow.runs":
                runs = data.get("dag_runs", [])
                if runs:
                    latest = runs[0]
                    facts.append(f"Latest training workflow {latest['dag_run_id']}: {latest['state']}.")
                    if latest["state"] == "failed":
                        task_args = args.model_copy(update={"run_id": latest["dag_run_id"]})
                        details = self.execute("airflow.tasks", task_args, request_id)
                        evidence.append(details)
                        if details.status == "ok":
                            for task in details.data.get("failed_tasks", []):
                                facts.append(f"Training task {task['task_id']} is {task['state']}.")
                                if task["state"] != "failed":
                                    continue  # Upstream-blocked tasks never started and have no execution log.
                                log_args = task_args.model_copy(update={"task_id": task["task_id"],
                                                                       "try_number": max(1, task.get("try_number", 1))})
                                evidence.append(self.execute("airflow.logs", log_args, request_id))
                        actions.append("Resolve the failed training task before requesting another run.")
                else:
                    unknowns.append("No recent training workflow is recorded.")
            elif name == "airflow.trigger":
                facts.append(f"Training run {data['dag_run_id']} was requested; state={data['state']}. "
                             "Completion must be checked separately.")
            else:
                facts.append(f"{name} returned recorded evidence.")
        if selected and "retrain" in request.message.lower():
            tags = selected.get("tags", {})
            reasons = []
            if tags.get("quality_gate") == "failed":
                reasons.append("the recorded quality gate failed")
            stamp = selected.get("start_time")
            if stamp and self.settings.freshness_days > 0:
                age = (datetime.now(timezone.utc).timestamp() * 1000 - stamp) / 86400000
                if age > self.settings.freshness_days:
                    reasons.append(f"run age {age:.1f} days exceeds the {self.settings.freshness_days}-day freshness policy")
            if tags.get("model.degradation") == "true":
                reasons.append("recorded model-degradation evidence is present")
            actions.append("Recommend retraining because " + "; ".join(reasons) + "."
                           if reasons else "Available evidence does not establish a need for retraining.")
            facts.append("No retraining was initiated by this assessment.")
        for result in evidence:
            if result.status != "ok" and not any(result.tool in u for u in unknowns):
                unknowns.append(f"{result.tool}: {result.error}")
        return ChatResponse(request_id=request_id, facts=facts, uncertainties=unknowns,
                            recommendations=actions, evidence=evidence)

    def tool_definitions(self):
        return [{"name": name, "permission": "confirm" if name in MUTATIONS else "read",
                 "input_schema": ToolArgs.model_json_schema()} for name in sorted(self.registry)]
