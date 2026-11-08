import math

from mlflow import MlflowClient


class MLflowTools:
    def __init__(self, settings, client=None):
        self.client = client or MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    @staticmethod
    def record(run):
        return {"run_id": run.info.run_id, "experiment_id": run.info.experiment_id,
                "status": run.info.status, "start_time": run.info.start_time,
                "metrics": run.data.metrics, "params": run.data.params, "tags": run.data.tags}

    def experiments(self, args):
        return {"experiments": [{"id": e.experiment_id, "name": e.name}
                                for e in self.client.search_experiments(max_results=args.limit)]}

    def runs(self, args):
        ids = args.experiment_ids or [e.experiment_id for e in self.client.search_experiments()]
        if not ids:
            return {"runs": []}
        return {"runs": [self.record(r) for r in self.client.search_runs(
            ids, max_results=args.limit, order_by=["attributes.start_time DESC"])]}

    def details(self, args):
        if not args.run_id:
            raise ValueError("run_id is required")
        run = self.record(self.client.get_run(args.run_id))
        run["artifacts"] = [{"path": a.path, "is_dir": a.is_dir}
                            for a in self.client.list_artifacts(args.run_id)]
        return run

    def best(self, args):
        recent = self.runs(args)["runs"]
        candidates = [r for r in recent if r["status"] == "FINISHED"
                      and args.metric in r["metrics"]
                      and math.isfinite(r["metrics"][args.metric])]
        selected = (sorted(candidates, key=lambda r: r["metrics"][args.metric],
                           reverse=args.direction == "max")[0] if candidates else None)
        return {"selected": selected, "comparison": recent, "metric": args.metric,
                "direction": args.direction, "window": args.limit,
                "selection_basis": "Metric ranking within recent runs; deployment needs a passed gate."}

    def compare(self, args):
        if len(args.run_ids) < 2:
            raise ValueError("Provide at least two run_ids")
        return {"runs": [self.record(self.client.get_run(r)) for r in args.run_ids]}

    def registry(self, args):
        if not args.model_name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid model name")
        versions = self.client.search_model_versions(f"name='{args.model_name}'")
        return {"versions": [{"name": v.name, "version": v.version, "run_id": v.run_id,
                              "status": v.status, "source": v.source} for v in versions]}
