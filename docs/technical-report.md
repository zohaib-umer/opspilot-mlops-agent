# OpsPilot: technical report

**Assignment 03 · MLOps & Production AI Engineering · Fall 2026**

## Objective and implementation

The system supports operational investigation across dataset, model, workflow and deployment layers. Python adapters expose 22 callable tools. A structured planner selects operations; an executor enforces permissions and attaches auditable evidence to every answer. [The architecture document](../architecture.md) contains the full component design, tool definitions and permission matrix.

The reference workload uses the 150-row Iris dataset, four numeric features and three classes. A fixed stratified holdout and a preprocessing/model pipeline make evaluation reproducible and avoid fitting normalization on the held-out partition. Macro F1 and accuracy are logged to MLflow together with parameters, model artifacts, committed Git identity and DVC content hash.

## Reproducibility and provenance

The CSV is tracked through `data/iris.csv.dvc`. Training reads this metadata at `HEAD` and compares its hash with the actual dataset bytes before logging provenance. The live demonstration pushes the data to a local DVC remote, creates a detached worktree, pulls the data there and compares hashes. The export `dvc-reproduction.json` records the result.

The model-selection tool ranks only finished recent runs with a finite requested metric. It supports maximization (F1/accuracy) and minimization (loss). Its comparison window and direction are included in the response. Candidate selection remains separate from the release gate.

## Orchestration and deployment

The Airflow 3 DAG has five dependent stages: validation, preprocessing, training, evaluation/MLflow and quality gate. The DAG has no automatic schedule, permits one active run, and retries tasks twice. Each run uses a distinct artifact directory. A failed gate records failure in MLflow and does not register or export a serving model.

The FastAPI container runs as a non-root user in a two-replica Deployment behind a ClusterIP Service. Requests and limits bound CPU/memory use. Liveness checks process availability; readiness requires an approved model to be loaded. A ConfigMap provides non-sensitive settings. Deployment annotations and the service version endpoint expose the model's recorded MLflow identity.

## Five demonstration conversations and evidence

The live verification script saves the actual request, response and tool results for each conversation. Files are indexed in [the evidence directory](../evidence/README.md). Successful pipeline completion is recorded separately from the trigger response.

| Scenario | Request | Evidence export |
|---|---|---|
| Dataset provenance | Identify the current dataset version and reproduce it | `01-dataset-provenance.json`, `dvc-reproduction.json` |
| Model selection | Find the best recent model based on F1 | `02-model-selection.json` |
| Pipeline execution | Trigger the training pipeline | `03-pipeline-request.json`, `03-pipeline-completion.json`, `03-pipeline-status.json` |
| Deployment diagnosis | Check Kubernetes deployment health | `04-deployment-diagnosis.json` |
| Multi-tool reasoning | Find the best recent model, identify its dataset, check deployment, and assess retraining | `05-multi-tool-assessment.json` |

Each response carries a request ID and per-tool status/duration. Recorded service failures remain explicit uncertainties. The multi-tool request does not start retraining. It can recommend retraining only when the selected model violates the configured age policy, has a failed gate, or has recorded degradation evidence.

A sixth verification uses an actual Ollama `qwen2.5:0.5b` model to produce a schema-constrained read-only plan and execute DVC operations. Its output is saved as `06-language-model-planning.json`; ordinary unit tests separately verify rejection of unauthorized model-selected operations.

## Failure investigation 1: rejected dataset validation

**Injection:** a real Airflow DAG run receives `inject_failure=validation`. The validation stage raises a schema-related exception, exercising task retries and downstream failure propagation.

**Diagnosis:** the agent reads the failed DAG run, retrieves task instances, identifies the failed/upstream-failed stages and requests available task logs. This locates the failure at the data-validation boundary rather than guessing that training or deployment failed.

**Root cause:** the deliberately injected missing-target-column condition prevents valid training inputs.

**Resolution:** trigger a new run without the injected fault. The script waits for a successful terminal state and exports the complete task status set. See `failure-01-validation.json`, `failure-01-agent-diagnosis.json`, and `failure-01-recovery.json`.

## Failure investigation 2: failed readiness after configuration change

**Injection:** the demonstration changes `MODEL_DIR` to `/missing` in the Deployment. New Pods start their API process but cannot load an approved model, so readiness returns HTTP 503.

**Diagnosis:** the agent correlates desired/ready replica counts, Pod conditions, probe events and container logs. Liveness and readiness are deliberately separate; a running process does not prove prediction availability.

**Root cause:** an invalid model-directory override causes the new revision to fail its readiness checks. Kubernetes retains healthy old replicas during the rolling update where possible, so this drill represents a blocked rollout rather than assuming a complete outage.

**Resolution:** remove the incorrect override, restore ConfigMap-based configuration and wait for the rollout to become available. See `failure-02-readiness.json` and `failure-02-recovery.json`.

## Testing and engineering controls

The test suite exercises plan selection, real function execution with mocked remote responses, service errors, timeout handling, input validation, namespace authorization, target-specific confirmation, missing provenance, secret redaction, deterministic training, failed quality gates and prediction readiness. CI runs linting and pytest on pull requests. The separate integration workflow runs actual services and exports evidence as a downloadable artifact.

## Known limitations and proposed improvements

This section is included because the assignment explicitly requires it.

| Current scope | Proposed improvement |
|---|---|
| The demonstration uses Iris and a single fixed holdout. | Add larger datasets, cross-validation and monitored distribution/performance drift. |
| Airflow standalone and SQLite-backed MLflow support a local demonstration. | Use managed Postgres, object storage, TLS and externally managed identities for shared environments. |
| The operator confirms writes with an exact phrase and API key. | Add per-user authorization, expiring action approvals and an audit database. |
| A timed-out remote request may complete after the caller stops waiting. | Add operation reconciliation and persistent idempotency keys before retries. |
| General natural-language planning depends on a separately running Ollama model; the built-in planner supports documented routes. | Expand evaluated intent coverage and add measured planner accuracy/regression benchmarks. |
| The deployment comparison uses immutable build intent recorded in annotations. | Verify image digests and query each serving replica's model identity before promotion. |
| Remote logs use pattern-based secret redaction. | Apply a service-specific allowlist and organization-wide log sanitization policy. |

## Engineering rationale

DVC/Git binds dataset content to source history; MLflow provides the supported experiment and registry API; Airflow models task dependencies/retries; Kubernetes reports observed application health. Keeping these responsibilities distinct produces traceable failure diagnosis. Evidence correlation preserves uncertainty instead of converting a missing service response into an unsupported operational claim.
