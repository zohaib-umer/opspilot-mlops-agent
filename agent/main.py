import logging
import secrets
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException

from agent.config import Settings
from agent.orchestrator import Orchestrator
from agent.schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
app = FastAPI(title="OpsPilot", version="1.0.0", description="Evidence-driven MLOps operations")


@lru_cache
def engine():
    return Orchestrator(Settings())


def authenticate(x_api_key: str = Header(default="")):
    expected = engine().settings.agent_api_key.get_secret_value()
    if not expected or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(status_code=401, detail="A configured agent API key is required")


@app.get("/health")
def health():
    return {"status": "ok", "service": "opspilot"}


@app.get("/tools", dependencies=[Depends(authenticate)])
def tools():
    return engine().tool_definitions()


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(authenticate)])
def chat(request: ChatRequest):
    return engine().chat(request)
