"""Verify structured planning with a running local language model and real DVC tools."""
import json
from pathlib import Path

from agent.config import Settings
from agent.orchestrator import Orchestrator
from agent.schemas import ChatRequest

settings = Settings(_env_file=None, ollama_url="http://localhost:11434",
                    llm_model="qwen2.5:0.5b", tool_timeout=120)
request = ChatRequest(message="Use dvc.status to inspect whether the tracked dataset has changed.")
response = Orchestrator(settings).chat(request)
assert response.evidence, response.uncertainties
assert all(item.status == "ok" for item in response.evidence), response.uncertainties
assert all(item.tool.startswith("dvc.") for item in response.evidence)
target = Path("evidence/live/06-language-model-planning.json")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"model": settings.llm_model, "request": request.model_dump(),
                              "response": response.model_dump()}, indent=2))
print("Structured language-model planning executed real DVC operations successfully.")
