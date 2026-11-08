# Demonstration and engineering defense

1. **Provenance:** inspect `data/iris.csv.dvc`, run the provenance conversation and show the selected Git commit. Open `dvc-reproduction.json` to demonstrate that a remote pull restored identical bytes.
2. **Selection:** open MLflow, compare macro F1 and accuracy, then ask for the best recent model. Explain the metric direction, the recent-run window and the distinction between a candidate and an approved release.
3. **Workflow:** submit a confirmed trigger, open Airflow and follow validation → preprocessing → training → evaluation → gate. Show the terminal task statuses rather than treating a successful HTTP request as successful training.
4. **Deployment:** inspect two ready Pods, the ClusterIP Service, probes, limits and ConfigMap. Call readiness and prediction endpoints, then compare model identity against the Deployment annotations.
5. **Integrated reasoning:** run the mandatory multi-tool question and inspect evidence from all four adapters. Explain why no training was automatically started.
6. **Failure defense:** open both failure exports, identify the failed boundary, show the relevant logs/conditions, and show recovery evidence.

## Questions to prepare

- Why is F1 alone insufficient for production readiness? It says nothing about freshness, data quality, serving health or deployment verification.
- How is a dataset linked to a run? A committed DVC pointer and verified byte hash are recorded as MLflow tags.
- What happens when MLflow is unavailable? The failed tool record is returned as uncertainty; no model or metric is invented.
- How are writes authorized? Typed input, an exact confirmation tied to a target, an allowlisted DAG/namespace and independent service credentials.
- Why separate liveness from readiness? A live API process can lack a usable model; routing traffic in that state would fail predictions.
- How does failure block release? Airflow dependencies require upstream success, and the gate refuses registration/export when the threshold is not met.
- What if an unexpected timeout occurs? Preserve the unknown outcome, inspect the target service and reconcile state before retrying a write.
