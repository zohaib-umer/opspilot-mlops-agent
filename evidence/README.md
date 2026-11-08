# Verification evidence

Start with [verified execution results](VERIFICATION.md) for the measured outcomes and direct links to the five conversations, both recovered failures and the reproducible dataset reference.

The **Live infrastructure verification** workflow exports actual responses from DVC/Git, MLflow, Airflow and Kubernetes into the `live-infrastructure-evidence` artifact. `execution.json` records the tested commit, capture time and environment. Files under `live/`, when present, are downloaded exports of that run.

| Record | Purpose |
|---|---|
| `01-dataset-provenance.json` | Dataset metadata, committed Git identity and reproduction instructions |
| `02-model-selection.json` | Recorded model metrics and candidate selection |
| `03-pipeline-*.json` | Confirmed trigger, terminal DAG/task states and subsequent agent inspection |
| `04-deployment-diagnosis.json` | Actual Deployments, Pods, Services and events |
| `05-multi-tool-assessment.json` | Correlated response covering all four technologies |
| `06-language-model-planning.json` | Actual Ollama structured planning followed by real DVC execution |
| `dvc-reproduction.json` | Original/restored hashes from a separate worktree |
| `failure-01-*.json` | Validation failure, agent diagnosis and successful rerun |
| `failure-02-*.json` | Failed readiness after configuration injection and restored rollout |
| `inference-readiness.json` | Readiness response reached through the cluster Service |
| `kubernetes.yaml` | Exported cluster objects |
| `unit-tests.xml` | Local automated test results, when present |

Mocked responses belong only to the automated unit tests. They are not presented as live infrastructure evidence.
