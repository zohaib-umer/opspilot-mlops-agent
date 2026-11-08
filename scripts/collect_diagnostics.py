"""Export sanitized Airflow diagnostics even when a live scenario aborts."""
import json
import os
import subprocess
from pathlib import Path

from agent.config import Settings
from agent.orchestrator import redact
from agent.schemas import ToolArgs
from agent.tools.airflow_tools import AirflowTools

result = {}
try:
    credentials = subprocess.check_output(
        ["docker", "compose", "exec", "-T", "airflow", "cat", "/opt/airflow/passwords.json"],
        text=True, stderr=subprocess.DEVNULL, timeout=10,
    )
    os.environ["AIRFLOW_PASSWORD"] = json.loads(credentials)["admin"]
    tools = AirflowTools(Settings(_env_file=None))
    result["import_errors"] = tools.request("GET", "/importErrors")
    result["runs"] = tools.runs(ToolArgs())
    result["details"] = []
    for run in result["runs"].get("dag_runs", []):
        args = ToolArgs(run_id=run["dag_run_id"])
        tasks = tools.tasks(args)
        entry = {"run_id": args.run_id, "tasks": tasks, "logs": []}
        for task in tasks.get("failed_tasks", []):
            if task["state"] != "failed":
                continue
            try:
                entry["logs"].append(tools.logs(args.model_copy(update={
                    "task_id": task["task_id"], "try_number": max(1, task.get("try_number", 1)),
                })))
            except Exception as exc:
                entry["logs"].append({"unavailable": type(exc).__name__})
        result["details"].append(entry)
except Exception as exc:
    result["diagnostic_error"] = type(exc).__name__
target = Path("evidence/live/airflow-diagnostics.json")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(redact(result), indent=2, default=str))
