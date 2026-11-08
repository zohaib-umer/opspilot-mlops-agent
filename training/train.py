import argparse
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import yaml
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

LOG = logging.getLogger(__name__)
FEATURES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]


def prepare_data(path="data/iris.csv"):
    iris = load_iris()
    frame = pd.DataFrame(iris.data, columns=FEATURES)
    frame["target"] = iris.target
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def validate(path):
    frame = pd.read_csv(path)
    if list(frame.columns) != FEATURES + ["target"]:
        raise ValueError("Dataset schema mismatch")
    if len(frame) < 30 or frame.isnull().any().any():
        raise ValueError("Dataset requires at least 30 complete rows")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("Dataset contains non-finite values")
    if set(frame.target.unique()) != {0, 1, 2} or (frame[FEATURES] <= 0).any().any():
        raise ValueError("Invalid class labels or feature values")
    LOG.info("Validated %d rows", len(frame))
    return {"path": str(path), "rows": len(frame)}


def preprocess(path, output="artifacts/work"):
    validate(path)
    frame = pd.read_csv(path)
    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURES], frame.target, test_size=0.25, random_state=42, stratify=frame.target,
    )
    Path(output).mkdir(parents=True, exist_ok=True)
    target = str(Path(output) / "split.joblib")
    joblib.dump((x_train, x_test, y_train, y_test), target)
    return target


def train(split, output="artifacts/work"):
    x_train, _, y_train, _ = joblib.load(split)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=300, random_state=42))
    model.fit(x_train, y_train)
    path = str(Path(output) / "model.joblib")
    joblib.dump(model, path)
    return path


def provenance(path):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    metadata_path = str(Path(path).with_suffix(Path(path).suffix + ".dvc"))
    # Read the metadata at the recorded commit, not an uncommitted workspace pointer.
    pointer = yaml.safe_load(subprocess.check_output(
        ["git", "show", f"{commit}:{metadata_path}"], text=True,
    ))
    expected = pointer["outs"][0]["md5"]
    actual = hashlib.md5(Path(path).read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError("Dataset bytes do not match committed DVC provenance")
    return {"git.commit": commit, "dvc.md5": actual, "dvc.path": path}


def evaluate(model_path, split, data_path, output="artifacts/work"):
    model = joblib.load(model_path)
    _, x_test, _, y_test = joblib.load(split)
    predicted = model.predict(x_test)
    metrics = {"f1": float(f1_score(y_test, predicted, average="macro")),
               "accuracy": float(accuracy_score(y_test, predicted))}
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment("opspilot-iris")
    with mlflow.start_run() as run:
        mlflow.log_params({"C": 1.0, "random_state": 42, "test_size": 0.25,
                           "estimator": "StandardScaler+LogisticRegression"})
        mlflow.set_tags(provenance(data_path))
        mlflow.set_tag("quality_gate", "pending")
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, "model", input_example=x_test.iloc[:2])
        result = {"run_id": run.info.run_id, "metrics": metrics,
                  "model_path": model_path, "output": output}
        Path(output, "metrics.json").write_text(json.dumps(metrics, indent=2))
        mlflow.log_artifact(str(Path(output) / "metrics.json"))
    return result


def quality_gate(result, threshold=0.90):
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    client = mlflow.MlflowClient()
    passed = result["metrics"]["f1"] >= threshold
    client.set_tag(result["run_id"], "quality_gate", "passed" if passed else "failed")
    client.set_tag(result["run_id"], "quality_gate.threshold", str(threshold))
    if not passed:
        raise ValueError(f"Quality gate failed: f1={result['metrics']['f1']:.4f} < {threshold}")
    # Only accepted runs receive a registered version and a serving bundle.
    version = mlflow.register_model(f"runs:/{result['run_id']}/model", "iris-classifier")
    bundle = Path(result["output"]) / "serving"
    bundle.mkdir(parents=True, exist_ok=True)
    model = joblib.load(result["model_path"])
    joblib.dump(model, bundle / "model.joblib")
    metadata = {"run_id": result["run_id"], "model_version": version.version,
                "quality_gate": "passed", "metrics": result["metrics"], "features": FEATURES}
    (bundle / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--data", default="data/iris.csv")
    parser.add_argument("--output", default="artifacts/work")
    parser.add_argument("--threshold", type=float, default=0.90)
    args = parser.parse_args()
    if args.prepare:
        print(prepare_data(args.data))
        return
    split = preprocess(args.data, args.output)
    model = train(split, args.output)
    print(json.dumps(quality_gate(evaluate(model, split, args.data, args.output), args.threshold), indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
