# Verified execution results

## Real infrastructure verification

The infrastructure scenarios were captured on **8 November 2026** from commit `10f8f43164bfc83df9eae7df292ff744784931ba` using actual Docker Compose services and a kind Kubernetes cluster. [The execution record](live/execution.json) identifies the environment and capture time. The source [GitHub run](https://github.com/zohaib-umer/assignment-03-mlops-agent/actions/runs/42471008440) completed the infrastructure scenarios; its subsequent, separate model-container download exhausted runner disk space. Language-model verification was moved to an independent runner.

| Check | Observed result | Record |
|---|---|---|
| Dataset provenance | Committed DVC metadata resolved successfully | [Dataset conversation](live/01-dataset-provenance.json) |
| Dataset reproduction | Original and restored MD5 both `4224576f0267bf88902f87f0f6200967` | [Remote-pull verification](live/dvc-reproduction.json) |
| Model selection | Macro F1 `0.92296296`, accuracy `0.92105263` | [Model comparison](live/02-model-selection.json) |
| Training pipeline | All five tasks reached `success` | [Terminal task states](live/03-pipeline-completion.json) |
| Deployment | Two desired replicas, two ready replicas | [Deployment conversation](live/04-deployment-diagnosis.json) |
| Multi-tool reasoning | DVC, MLflow, Airflow and Kubernetes calls all returned `ok`; no retraining initiated | [Integrated assessment](live/05-multi-tool-assessment.json) |
| Validation failure | Validation failed on attempt 3; all four downstream tasks were `upstream_failed` with zero attempts | [Failure states](live/failure-01-validation.json) |
| Validation recovery | New DAG run completed successfully | [Recovery run](live/failure-01-recovery.json) |
| Readiness failure | New revision could not load the model from `/missing`; healthy old replicas remained available | [Pod logs and events](live/failure-02-readiness.json) |
| Deployment recovery | Generation 4 observed; two updated and ready replicas | [Recovered deployment](live/failure-02-recovery.json) |
| In-cluster serving | ClusterIP readiness endpoint returned `ready` and a passed model gate | [Serving response](live/inference-readiness.json) |

The integrated assessment correctly identified that the newly trained best candidate differed from the model already deployed. Model ranking did not automatically promote the newer candidate or start another training run.

The recovery snapshot briefly includes a retiring Pod from the failed revision alongside the two healthy serving replicas. The final adapter exposes Pod termination state, and a regression test confirms that a retiring Pod does not cause a false unhealthy-deployment recommendation. Raw captured responses remain unchanged and identify their tested source commit.

## Live language-model verification

The independent [planner verification run](https://github.com/zohaib-umer/assignment-03-mlops-agent/actions/runs/42501784787) completed successfully. An actual Ollama `qwen2.5:0.5b` model selected `dvc.datasets` and `dvc.status`; both operations executed against the versioned repository and returned `ok`. The response reported no uncertainties. See [the complete request, plan execution and evidence](live/06-language-model-planning.json).

## Automated and local verification

- **29 automated tests passed**; see [JUnit results](unit-tests.xml).
- Ruff lint checks passed.
- A separate local training execution registered an accepted model with the same evaluation metrics; see [local training](local-training.json).
- External services are mocked only in ordinary unit tests. The records in `live/` are real service responses.
