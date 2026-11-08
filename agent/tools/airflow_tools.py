from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

import httpx


class AirflowTools:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(base_url=settings.airflow_url,
                                            timeout=settings.tool_timeout)

    def request(self, method, path, **kwargs):
        token = self.settings.airflow_token.get_secret_value()
        if not token:
            response = self.client.post("/auth/token", json={
                "username": self.settings.airflow_username,
                "password": self.settings.airflow_password.get_secret_value(),
            })
            response.raise_for_status()
            token = response.json()["access_token"]
        response = self.client.request(method, "/api/v2" + path,
                                       headers={"Authorization": f"Bearer {token}"}, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def dag_path(args):
        return f"/dags/{quote(args.dag_id, safe='')}"

    def dags(self, args):
        return self.request("GET", "/dags", params={"limit": args.limit})

    def runs(self, args):
        return self.request("GET", self.dag_path(args) + "/dagRuns",
                            params={"limit": args.limit, "order_by": "-logical_date"})

    def trigger(self, args):
        if args.dag_id != self.settings.approved_dag:
            raise PermissionError("DAG is not approved")
        return self.request("POST", self.dag_path(args) + "/dagRuns", json={
            "dag_run_id": "opspilot__" + uuid4().hex,
            "logical_date": datetime.now(timezone.utc).isoformat(), "conf": {},
        })

    def tasks(self, args):
        if not args.run_id:
            raise ValueError("run_id is required")
        result = self.request("GET", self.dag_path(args) +
                              f"/dagRuns/{quote(args.run_id, safe='')}/taskInstances")
        result["failed_tasks"] = [t for t in result.get("task_instances", [])
                                  if t.get("state") in {"failed", "upstream_failed"}]
        return result

    def logs(self, args):
        if not args.run_id or not args.task_id:
            raise ValueError("run_id and task_id are required")
        path = (self.dag_path(args) + f"/dagRuns/{quote(args.run_id, safe='')}"
                f"/taskInstances/{quote(args.task_id, safe='')}/logs/{args.try_number}")
        return self.request("GET", path)
