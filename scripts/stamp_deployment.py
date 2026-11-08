import json
import subprocess
from pathlib import Path

metadata = json.loads(Path("artifacts/work/serving/metadata.json").read_text())
patch = {"spec": {"template": {"metadata": {"annotations": {
    "opspilot/model-run-id": metadata["run_id"],
    "opspilot/model-version": str(metadata["model_version"]),
}}}}}
subprocess.run(["kubectl", "patch", "deployment", "prediction-api", "-n", "mlops",
                "--type", "merge", "-p", json.dumps(patch)], check=True)
