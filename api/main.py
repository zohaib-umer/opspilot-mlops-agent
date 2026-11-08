import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from training.train import FEATURES


@asynccontextmanager
async def lifespan(app):
    root = Path(os.getenv("MODEL_DIR", "/app/model"))
    app.state.model = None
    app.state.metadata = {}
    try:
        metadata = json.loads((root / "metadata.json").read_text())
        if metadata.get("quality_gate") != "passed":
            raise ValueError("Model did not pass quality gate")
        app.state.model = joblib.load(root / "model.joblib")
        app.state.metadata = metadata
    except (OSError, ValueError) as exc:
        logging.getLogger("opspilot.inference").warning(
            "Approved model unavailable at %s (%s)", root, type(exc).__name__,
        )
    yield


app = FastAPI(title="OpsPilot Prediction API", version="1.0.0", lifespan=lifespan)


class Features(BaseModel):
    sepal_length: float = Field(gt=0, le=30, allow_inf_nan=False)
    sepal_width: float = Field(gt=0, le=30, allow_inf_nan=False)
    petal_length: float = Field(gt=0, le=30, allow_inf_nan=False)
    petal_width: float = Field(gt=0, le=30, allow_inf_nan=False)


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    if app.state.model is None:
        raise HTTPException(503, "Approved model is not loaded")
    return {"status": "ready", **app.state.metadata}


@app.get("/version")
def version():
    return {"application": os.getenv("APP_VERSION", "1.0.0"), **app.state.metadata}


@app.post("/predict")
def predict(features: Features):
    ready()
    frame = pd.DataFrame([features.model_dump()], columns=FEATURES)
    prediction = int(app.state.model.predict(frame)[0])
    return {"class_id": prediction, "class_name": ["setosa", "versicolor", "virginica"][prediction],
            "run_id": app.state.metadata["run_id"]}
