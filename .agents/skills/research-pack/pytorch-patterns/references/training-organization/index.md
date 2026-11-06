# Training Organization

Use this guide for training lifecycle design, Lightning projects, and checkpoint/recovery reviews. For an explicit loop, also read [custom training](../custom-training/index.md).

## Assign each responsibility an owner

For Lightning projects, follow the official Style Guide:

- Keep the reusable network in `nn.Module`. Give `forward` the inference contract: input/output tensors and their shapes.
- Put task loss, training/validation/test steps, metric updates, and optimizer/scheduler definitions in `LightningModule`.
- Put dataset preparation, splits, transforms, and loaders in `LightningDataModule` when shared data logic warrants it. Use `prepare_data` for one-time work and `setup` for per-process construction according to Lightning's lifecycle.
- Use `Trainer` for the selected device strategy, precision, loop execution, accumulation, and checkpoint callbacks. Under automatic optimization, let Lightning own backward, scaling, and optimizer stepping.
- Use a callback for behavior that spans training lifecycle hooks and is independently reusable. Keep a short task-specific operation next to the task when that is clearer.

Make constructor dependencies explicit, with meaningful types and defaults. Keep a network loadable for inference without constructing datasets, loggers, or a Trainer.

For a project already using an explicit loop, establish the same ownership in its existing functions. Evaluate a framework migration against a concrete maintenance or execution requirement.

## Define the metric and selection contract

Specify the data split, prediction/target interpretation, aggregation, direction of improvement, and checkpoint selection metric. Use validation results for model selection and the held-out test split for final evaluation.

Aggregate counts or sufficient statistics according to the metric. For example, global IoU depends on accumulated intersections and unions; a mean of per-batch IoUs gives different weighting. Weight mean losses by their relevant sample, token, or pixel counts. Include distributed reduction in the metric's owner and prevent padded evaluation samples from changing the result.

Keep best score, best epoch, selected checkpoint, and reported metrics consistent across normal training and recovery. Make the handling of an empty loader or invalid metric explicit.

## Checkpoint and resume contract

Define whether recovery is supported at an epoch boundary or within an epoch. Identify these operations separately:

- **New run:** create an independent run ID and output directory.
- **Initialize from weights:** load compatible network parameters and start new optimizer/progress state.
- **Resume:** continue the same compatible experiment with its training state and log identity.

For Lightning, use `Trainer.fit(..., ckpt_path=...)` for training recovery. Loading a `LightningModule` from a checkpoint alone does not restore a Trainer's optimizer and loop state.

Inventory the active state owners: model, optimizer, scheduler, AMP scaler, loop progress, best-metric/early-stop callbacks, custom stateful components, and the project's RNG/sampler strategy. Lightning checkpoints contain framework-managed training state and support stateful callbacks/data modules. Preserve project-owned state through the appropriate checkpoint/state interfaces.

Seed initialization is useful when starting a run. Exact replay after an interruption also needs a tested data-order and augmentation strategy. Account for DataLoader workers, prefetch, persistent workers, sampler progress, and RNG state at the chosen recovery boundary. State the hardware/software conditions under which replay was verified.

Before writing into an existing run directory, read its checkpoint and run metadata and check compatibility: configuration, actual split identity, selection metric, and relevant environment constraints. Validate first, then record the continuation. Record interruptions as interrupted and failures as failed; mark success when training completes under the project's completion rule.

Store deployable weights and resumable training checkpoints with clear roles. Write checkpoints through the framework's storage path or a suitable temporary-file-and-replace strategy. Keep the previous usable recovery point if a new save fails.

## Verify the behavior that changed

Use a small real training path to check the affected lifecycle. For recovery changes, exercise interruption/resume, including a resumed epoch that does not improve the best metric. Compare progress, learning rate, selected checkpoint, state, and log continuity. Assert matching weights only when the project promises deterministic replay under the tested conditions.

For model/loss/data changes, inspect batch shapes and labels, run a short train/validation cycle, and use a one-batch overfit check when useful for the task. Keep evaluation and export load paths in the affected checks.

## Sources

- [Lightning Style Guide](https://lightning.ai/docs/pytorch/stable/reference/starter/style_guide)
- [Lightning checkpoint contents and restoration](https://lightning.ai/docs/pytorch/stable/common/checkpointing_basic.html)
- [Lightning DataModule lifecycle](https://lightning.ai/docs/pytorch/stable/data/datamodule.html)
- [PyTorch reproducibility and DataLoader randomness](https://docs.pytorch.org/docs/stable/notes/randomness.html)
- [PyTorch AMP saving and resuming](https://docs.pytorch.org/tutorials/recipes/recipes/amp_recipe.html#saving-resuming)
