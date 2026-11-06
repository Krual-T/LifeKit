# TensorBoard and CSV

Read this file when extending the project's existing local curve or tabular logging.

## TensorBoard

Use a distinct log directory for each new run. Record scalar values with the actual `SummaryWriter.add_scalar` API:

```python
writer.add_scalar("train/loss", loss_value, global_step=optimizer_step)
writer.add_scalar("val/dice", validation_dice, global_step=optimizer_step)
```

The step parameter is `global_step`. Use the project's chosen metric axis consistently and document it. Use stable tags and image sampling rules so comparable runs produce comparable records.

When resuming into an existing directory, align the writer's step with the recovered checkpoint. `SummaryWriter(purge_step=T)` can hide events with step >= T when recovery returns to step T. Determine T from the project's checkpoint/next-step convention and verify the displayed history. Use the training framework's supported logger lifecycle when it owns the writer.

Call `flush` and `close` through the logger lifecycle or cleanup path. Keep configuration and run identity in a structured sidecar or the project's established metadata store so event files remain interpretable.

## CSV

Use explicit columns such as `run_id`, `epoch`, `global_step`, `split`, metric values, and relevant timing/learning rate. Choose a documented row granularity and aggregation convention.

Keep new-run output separate. For resume, inspect the installed CSV logger's append and version-directory behavior. Decide how to handle rows beyond the recovered checkpoint and verify the persisted result. Retain useful earlier rows while making continuation segments or replacement behavior explicit.

With Lightning, reuse `CSVLogger` and `TensorBoardLogger` when they fit the project. Verify where logger versions and Hydra output directories place files; associate them with the training run's identity deliberately.

## Sources

- [PyTorch SummaryWriter, add_scalar, purge_step, flush, and close](https://docs.pytorch.org/docs/stable/tensorboard.html)
- [Lightning CSVLogger](https://lightning.ai/docs/pytorch/stable/api/lightning.pytorch.loggers.csv_logs.CSVLogger.html)
- [Lightning TensorBoardLogger](https://lightning.ai/docs/pytorch/stable/api/lightning.pytorch.loggers.tensorboard.TensorBoardLogger.html)
