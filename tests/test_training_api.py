import json
from unittest.mock import Mock

import joblib
import pytest
from fastapi.testclient import TestClient

from api.main import app
from training import train


def test_validation_rejects_missing_target(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("sepal_length\n5.1\n")
    with pytest.raises(ValueError, match="schema"):
        train.validate(path)


def test_reproducible_split_and_model(tmp_path):
    path = train.prepare_data(tmp_path / "iris.csv")
    split = train.preprocess(path, tmp_path)
    model_path = train.train(split, tmp_path)
    model = joblib.load(model_path)
    _, x_test, _, y_test = joblib.load(split)
    assert train.f1_score(y_test, model.predict(x_test), average="macro") >= 0.90


def test_failed_gate_cannot_register_or_publish_model(monkeypatch, tmp_path):
    client, register = Mock(), Mock()
    monkeypatch.setattr(train.mlflow, "MlflowClient", lambda: client)
    monkeypatch.setattr(train.mlflow, "register_model", register)
    result = {"run_id": "bad", "metrics": {"f1": 0.2}, "output": str(tmp_path)}
    with pytest.raises(ValueError, match="Quality gate failed"):
        train.quality_gate(result)
    register.assert_not_called()
    assert not (tmp_path / "serving").exists()
    client.set_tag.assert_any_call("bad", "quality_gate", "failed")


def test_missing_model_is_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_prediction_and_input_validation(monkeypatch, tmp_path):
    path = train.prepare_data(tmp_path / "iris.csv")
    train.train(train.preprocess(path, tmp_path), tmp_path)
    (tmp_path / "metadata.json").write_text(json.dumps({"quality_gate": "passed", "run_id": "test"}))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        result = client.post("/predict", json={"sepal_length": 5.1, "sepal_width": 3.5,
                                               "petal_length": 1.4, "petal_width": 0.2})
        assert result.json()["class_name"] == "setosa"
        assert client.post("/predict", json={"sepal_length": -1}).status_code == 422


def test_provenance_uses_committed_pointer_and_verifies_bytes(monkeypatch, tmp_path):
    path = tmp_path / "iris.csv"
    path.write_bytes(b"verified dataset\n")
    digest = train.hashlib.md5(path.read_bytes()).hexdigest()
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        return "a" * 40 if args[1] == "rev-parse" else f"outs:\n- md5: {digest}\n"

    monkeypatch.setattr(train.subprocess, "check_output", git)
    result = train.provenance(path)
    assert result["dvc.md5"] == digest
    assert "\\" not in calls[1][-1]
    path.write_bytes(b"modified dataset\n")
    with pytest.raises(ValueError, match="do not match"):
        train.provenance(path)
