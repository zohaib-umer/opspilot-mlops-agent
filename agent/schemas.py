from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = "HEAD"
    other_revision: str = "HEAD"
    run_id: str | None = None
    run_ids: list[str] = Field(default_factory=list, max_length=20)
    experiment_ids: list[str] = Field(default_factory=list, max_length=20)
    metric: str = Field(default="f1", pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    direction: Literal["max", "min"] = "max"
    limit: int = Field(default=5, ge=1, le=100)
    dag_id: str = "training_pipeline"
    task_id: str | None = None
    try_number: int = Field(default=1, ge=1)
    pod: str | None = None
    namespace: str = "mlops"
    model_name: str = "iris-classifier"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=3, max_length=4000)
    arguments: ToolArgs = Field(default_factory=ToolArgs)
    confirmation: str | None = None


class ToolResult(BaseModel):
    tool: str
    status: Literal["ok", "error", "denied", "timeout"]
    data: Any = None
    error: str | None = None
    duration_ms: float
    request_id: str


class ChatResponse(BaseModel):
    request_id: str
    facts: list[str]
    uncertainties: list[str]
    recommendations: list[str]
    evidence: list[ToolResult]
