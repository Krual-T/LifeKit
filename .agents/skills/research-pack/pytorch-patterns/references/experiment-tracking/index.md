# Experiment Tracking

Use this guide for training logs, run comparison, and recovery continuity. Inspect the project's existing logger and storage location first.

## Select a backend for the actual task

| Need | Read next |
| --- | --- |
| Local curves, images, or tabular results using TensorBoard/CSV | [TensorBoard and CSV](tensorboard-csv.md) |
| Searchable run parameters, metrics, and artifacts across experiments using MLflow | [MLflow](mlflow.md) |
| An existing W&B, Trackio, Comet, or another working backend | Apply the common recording contract using that backend's installed API |

Keep the current backend when it meets the requirement. Centralized tracking becomes useful when runs need querying and comparison across models, datasets, scenes, or seeds. Choose storage and synchronization appropriate to the project's data policy.

## Give a run an identity

Associate an independent run ID with the effective configuration, source revision, environment specification, dataset release or actual split manifests, selection metric, seeds, and artifact location. Use names/tags to aid comparison while retaining stable IDs.

New experiments receive new run identities. Initialization from existing weights records that lineage and starts new training state. Resume reuses an identity only after the original experiment has passed compatibility checks; see [training organization](../training-organization/index.md#checkpoint-and-resume-contract).

## Make metrics comparable

- Name training, validation, and test metrics distinctly, with clear units and direction of improvement.
- Choose and record the step axis: epoch, optimizer update/global step, samples, or another task-defined unit. Accumulation and multiple optimizers can make batch index differ from optimizer updates.
- Aggregate by the relevant sample/token/pixel count. For non-additive metrics, aggregate sufficient statistics through the metric implementation.
- Distinguish a local process measurement from a global training metric. Perform required collective reductions with all participating ranks, then write from the designated logging process.
- Keep chart values numeric; handle non-finite metrics explicitly. Record learning rate and meaningful throughput/timing measurements when they help diagnose the run.
- Use representative, bounded image/artifact logging where it helps validate predictions and labels.

## Keep state and artifacts truthful

Keep best metrics associated with the selected checkpoint and its epoch/step. Record whether the run completed, failed, or was interrupted. Record a continuation event when resuming.

Before recovery writes, reconcile the chosen checkpoint's progress with the existing log history. A checkpoint may precede already-written metrics. Use the backend's supported continuation or purge mechanism where available; otherwise record separate continuation segments and their relationship so comparisons do not silently mix duplicate steps.

Flush and close local writers through the training framework or a reliable cleanup path. Include log-writing failures in the run's diagnostics. Preserve valid checkpoints when the logger fails.

## Verify the recording path

For a logging change, use a short run to inspect names, axes, aggregation, config/identity records, and artifact locations. For recovery changes, continue a saved checkpoint and check the next step, learning rate, metrics, and final status. Inspect the persisted records rather than relying only on console output.

## Sources

- [Lightning logging and supported backends](https://lightning.ai/docs/pytorch/stable/extensions/logging.html)
- [MLflow experiment tracking](https://mlflow.org/docs/latest/tracking/)
- [PyTorch TensorBoard API](https://docs.pytorch.org/docs/stable/tensorboard.html)
