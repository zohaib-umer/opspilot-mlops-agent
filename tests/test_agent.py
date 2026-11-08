import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from agent.config import Settings
from agent.orchestrator import Orchestrator, redact
from agent.schemas import ChatRequest, ToolArgs
from agent.tools.airflow_tools import AirflowTools
from agent.tools.dvc_tools import DVCTools
from agent.tools.kubernetes_tools import KubernetesTools
from agent.tools.mlflow_tools import MLflowTools


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_multi_tool_plan_never_triggers_training():
    engine = Orchestrator(settings(), {})
    plan = engine.plan("Find the best recent model, identify the dataset version, check deployment and explain whether retraining is necessary")
    assert {name.split('.')[0] for name in plan} == {"mlflow", "dvc", "kubernetes", "airflow"}
    assert "airflow.trigger" not in plan


def test_successful_tool_execution_and_structured_log(caplog):
    engine = Orchestrator(settings(), {"dvc.status": lambda a: {"changes": {}}})
    with caplog.at_level(logging.INFO, logger="opspilot.tools"):
        result = engine.execute("dvc.status", ToolArgs(), "request-123")
    assert result.status == "ok"
    entry = json.loads(caplog.records[-1].message)
    assert entry["request_id"] == "request-123"
    assert entry["duration_ms"] >= 0
    assert entry["tool"] == "dvc.status"


def test_timeout_is_explicit():
    engine = Orchestrator(settings(tool_timeout=0.01), {"slow": lambda a: time.sleep(0.05)})
    result = engine.execute("slow", ToolArgs(), "r")
    assert result.status == "timeout"
    assert result.data is None


def test_service_failure_does_not_invent_results():
    failure = Mock(side_effect=ConnectionError("password=super-secret"))
    engine = Orchestrator(settings(), {"mlflow.best": failure})
    reply = engine.chat(ChatRequest(message="Find the best model"))
    assert not reply.facts
    assert reply.uncertainties
    assert reply.evidence[0].data is None
    assert "super-secret" not in reply.model_dump_json()


def test_invalid_request_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(message="x")
    with pytest.raises(ValidationError):
        ToolArgs(limit=0)
    with pytest.raises(ValidationError):
        ToolArgs(metric="f1; drop database")


def test_restart_requires_confirmation():
    restart = Mock()
    engine = Orchestrator(settings(), {"kubernetes.restart": restart})
    result = engine.execute("kubernetes.restart", ToolArgs(), "r")
    assert result.status == "denied"
    restart.assert_not_called()


def test_namespace_rejected_even_when_confirmed():
    restart = Mock()
    engine = Orchestrator(settings(), {"kubernetes.restart": restart})
    result = engine.execute("kubernetes.restart", ToolArgs(namespace="production"), "r",
                            "CONFIRM kubernetes.restart production/prediction-api")
    assert result.status == "denied"
    restart.assert_not_called()


def test_approved_restart_executes_once():
    restart = Mock(return_value={"requested": "restart"})
    engine = Orchestrator(settings(), {"kubernetes.restart": restart})
    result = engine.execute("kubernetes.restart", ToolArgs(), "r",
                            "CONFIRM kubernetes.restart mlops/prediction-api")
    assert result.status == "ok"
    restart.assert_called_once()


def test_airflow_unapproved_dag_rejected():
    trigger = Mock()
    engine = Orchestrator(settings(), {"airflow.trigger": trigger})
    result = engine.execute("airflow.trigger", ToolArgs(dag_id="delete_everything"), "r",
                            "CONFIRM airflow.trigger delete_everything")
    assert result.status == "denied"
    trigger.assert_not_called()


def test_airflow_uses_v2_and_bearer_token():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"dags": []})

    client = httpx.Client(base_url="http://airflow", transport=httpx.MockTransport(handler))
    tools = AirflowTools(settings(airflow_token="private"), client)
    assert tools.dags(ToolArgs()) == {"dags": []}
    assert calls[0].url.path == "/api/v2/dags"
    assert calls[0].headers["Authorization"] == "Bearer private"


def test_best_run_ignores_failed_and_missing_metrics():
    def run(identifier, state, metrics):
        return SimpleNamespace(info=SimpleNamespace(run_id=identifier, experiment_id="1",
                                                     status=state, start_time=1),
                               data=SimpleNamespace(metrics=metrics, params={}, tags={}))
    client = Mock()
    client.search_runs.return_value = [run("failed", "FAILED", {"f1": 1}),
                                       run("missing", "FINISHED", {}),
                                       run("valid", "FINISHED", {"f1": 0.9})]
    tools = MLflowTools(settings(), client)
    assert tools.best(ToolArgs(experiment_ids=["1"]))["selected"]["run_id"] == "valid"


def test_best_run_can_minimize_loss():
    client = Mock()
    tools = MLflowTools(settings(), client)
    tools.runs = lambda a: {"runs": [
        {"run_id": "a", "status": "FINISHED", "metrics": {"loss": 0.4}},
        {"run_id": "b", "status": "FINISHED", "metrics": {"loss": 0.1}},
    ]}
    assert tools.best(ToolArgs(metric="loss", direction="min"))["selected"]["run_id"] == "b"


def test_dvc_revision_rejects_command_injection():
    tools = DVCTools(settings())
    with pytest.raises(ValueError):
        tools.revision("HEAD; whoami")
    with pytest.raises(ValueError):
        tools.revision("--help")


def test_kubernetes_rejects_namespace_before_connecting():
    tools = KubernetesTools(settings())
    with pytest.raises(PermissionError):
        tools.pods(ToolArgs(namespace="kube-system"))


def test_missing_run_provenance_never_uses_current_head():
    version = Mock()
    registry = {"mlflow.details": lambda a: {"run_id": "r", "tags": {}}, "dvc.version": version}
    reply = Orchestrator(settings(), registry).chat(
        ChatRequest(message="Which dataset was used for experiment?", arguments=ToolArgs(run_id="r")))
    version.assert_not_called()
    assert any("provenance" in u for u in reply.uncertainties)


def test_redaction_removes_secrets_from_nested_service_logs():
    value = redact({"token": "private", "logs": ["Authorization: Bearer abc.xyz", "password=private"]})
    assert "private" not in json.dumps(value)
    assert "abc.xyz" not in json.dumps(value)


def test_unknown_request_is_not_routed_to_infrastructure():
    reply = Orchestrator(settings(), {}).chat(ChatRequest(message="Tell me a joke"))
    assert not reply.evidence
    assert reply.uncertainties


def test_structured_planner_only_accepts_allowlisted_read_tools(monkeypatch):
    response = Mock()
    response.json.return_value = {"message": {"content": '{"tools":["kubernetes.restart"]}'}}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: response)
    engine = Orchestrator(settings(ollama_url="http://localhost:11434"),
                          {"dvc.status": Mock(), "kubernetes.restart": Mock()})
    with pytest.raises(ValueError, match="invalid tool"):
        engine.plan("Inspect data")


def test_structured_planner_selects_and_executes_read_tool(monkeypatch):
    response = Mock()
    response.json.return_value = {"message": {"content": '{"tools":["dvc.status"]}'}}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: response)
    read = Mock(return_value={"changes": {}})
    reply = Orchestrator(settings(ollama_url="http://localhost:11434"), {"dvc.status": read}).chat(
        ChatRequest(message="Inspect my data changes"))
    assert reply.evidence[0].status == "ok"
    read.assert_called_once()


def test_comparison_honors_explicit_run_ids():
    compare = Mock(return_value={"runs": []})
    engine = Orchestrator(settings(), {"mlflow.compare": compare})
    engine.chat(ChatRequest(message="Compare experiments", arguments=ToolArgs(run_ids=["a", "b"])))
    assert compare.call_args.args[0].run_ids == ["a", "b"]


def test_agent_api_requires_configured_key(monkeypatch):
    from fastapi.testclient import TestClient

    from agent import main

    monkeypatch.setattr(main, "engine", lambda: Orchestrator(settings(agent_api_key="test-key"), {}))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tools").status_code == 401
        assert client.get("/tools", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/tools", headers={"X-API-Key": "test-key"}).status_code == 200
