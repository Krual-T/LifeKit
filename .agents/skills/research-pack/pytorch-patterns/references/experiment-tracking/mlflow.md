# MLflow

Read this file when adopting or extending MLflow experiment tracking. Use the API and storage configuration for the installed MLflow version.

## Define experiments and runs

Use an experiment to group related runs. Give each independent training invocation a new run, with searchable parameters and tags for model, data release/split, scenario, and seed. Store the effective configuration, environment specification, evaluation output, and relevant checkpoints as artifacts or references to managed artifacts.

MLflow can start with local storage. Use the project's tracking URI, backend store, and artifact location explicitly when shared comparison is needed. Validate which files and metadata may be published to that destination.

## Log through one owner

Use `start_run`, `log_params`, `log_metrics`, and `log_artifact`/`log_artifacts` through the project's tracking integration. In Lightning, evaluate `MLFlowLogger` before writing a parallel manual integration.

Keep immutable run parameters stable. Record a changing value such as learning rate as a metric with the chosen step axis, and use tags or artifacts for contextual records as appropriate.

Perform distributed metric reduction with all required ranks, then let the designated logging owner write the global result. Avoid combining automatic and manual logging for the same metric unless ownership is explicit.

## Continue a run deliberately

To resume the same compatible experiment, retain its MLflow run ID and use the backend's continuation API, such as `start_run(run_id=...)`. Reconcile the recovered checkpoint's progress with persisted metric steps first. MLflow permits multiple logged values at the same step; define how continuation records are queried and displayed if the checkpoint predates existing metrics.

Use a new run for changed data splits, selection metrics, or intentional weight initialization. Record parent/source lineage when useful. Keep training interruption/failure/completion reflected in run status or explicit status metadata through the logger lifecycle.

## Verify the integration

Run a short training job, query its parameters and metric history, and load an artifact from its actual destination. When changing resume, check that the intended run ID is continued and that the step history matches the recorded continuation policy.

## Sources

- [MLflow Tracking concepts and storage](https://mlflow.org/docs/latest/tracking/)
- [MLflow Tracking API](https://mlflow.org/docs/latest/tracking/tracking-api/)
- [Lightning MLFlowLogger](https://lightning.ai/docs/pytorch/stable/api/lightning.pytorch.loggers.mlflow.MLFlowLogger.html)
