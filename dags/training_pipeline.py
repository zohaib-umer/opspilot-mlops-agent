import hashlib
import logging
from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, get_current_context, task

from training.train import evaluate, preprocess, quality_gate, train, validate


@dag(dag_id="training_pipeline", start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
     schedule=None, catchup=False, max_active_runs=1,
     default_args={"retries": 2, "retry_delay": timedelta(seconds=10)},
     tags=["opspilot", "training"])
def training_pipeline():
    @task
    def validation():
        context = get_current_context()
        conf = context["dag_run"].conf or {}
        if conf.get("inject_failure") == "validation":
            raise ValueError("Injected validation failure: required target column missing")
        logging.info("Validating versioned dataset")
        validate("data/iris.csv")
        run_key = hashlib.sha256(context["run_id"].encode()).hexdigest()[:16]
        return {"path": "data/iris.csv", "output": f"artifacts/{run_key}",
                "threshold": float(conf.get("threshold", 0.90))}

    @task
    def preprocessing(config):
        return {**config, "split": preprocess(config["path"], config["output"])}

    @task
    def training(config):
        return {**config, "model": train(config["split"], config["output"])}

    @task
    def evaluation_mlflow(config):
        return {**evaluate(config["model"], config["split"], config["path"], config["output"]),
                "threshold": config["threshold"]}

    @task
    def gate(result):
        return quality_gate(result, result["threshold"])

    gate(evaluation_mlflow(training(preprocessing(validation()))))


training_pipeline()
