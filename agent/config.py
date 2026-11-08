from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    repo_path: Path = Path(".")
    mlflow_tracking_uri: str = "http://localhost:5000"
    airflow_url: str = "http://localhost:8080"
    airflow_username: str = "admin"
    airflow_password: SecretStr = SecretStr("")
    airflow_token: SecretStr = SecretStr("")
    approved_dag: str = "training_pipeline"
    kube_namespace: str = "mlops"
    kube_deployment: str = "prediction-api"
    agent_api_key: SecretStr = SecretStr("")
    ollama_url: str = ""
    llm_model: str = "qwen2.5:7b"
    freshness_days: int = 30
    tool_timeout: float = 15
