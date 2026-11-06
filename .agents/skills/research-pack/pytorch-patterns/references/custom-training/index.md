# Custom Training with PyTorch and Accelerate

Use this guide when keeping an explicit training loop, or when adding mixed precision, distributed execution, or gradient accumulation with Accelerate. Preserve a working native loop when it already meets the task.

## Keep loop ownership explicit

Organize a native loop around reusable model/data/loss/metric components and explicit train, evaluate, checkpoint, and run-recording functions. Keep the network usable for inference independently of the training runtime.

For an Accelerate integration:

1. Construct `Accelerator` with the selected precision, accumulation, and tracking settings.
2. Prepare model, optimizer, loaders, and the relevant scheduler through `accelerator.prepare` as appropriate for the selected strategy.
3. Use `accelerator.backward(loss)` and the documented accumulation context. Let prepared optimizers and schedulers follow Accelerate's stepping behavior.
4. Clip gradients through Accelerate at synchronized update boundaries when clipping is enabled.
5. Evaluate using the prepared execution path and correctly aggregated metrics.

Keep device placement, precision, backward, optimizer updates, and synchronization under a clear owner. Add Accelerate to a native loop as a deliberate integration; a Lightning `Trainer` already owns these responsibilities.

## Accumulation and metrics

Use `accelerator.accumulate(model)` with the configured accumulation steps and follow the installed version's optimizer/scheduler semantics. Log optimizer updates/global step according to the project's actual update boundary. Check the handling of the final partial accumulation window.

Aggregate metrics across processes before writing global values. `accelerator.gather_for_metrics` helps gather predictions/targets and handle duplicate final-batch samples under supported loader settings. Use count-weighted reductions for additive statistics and the metric's required state for non-additive metrics. All ranks needed by a collective must participate.

Use the documented tracker integration (`init_trackers`, `log`, `end_training`) when appropriate. Accelerate manages supported tracker process behavior; keep collective operations outside a main-process-only conditional. For metric schemas and run identity, read [experiment tracking](../experiment-tracking/index.md).

## Checkpoint and recovery

Use `accelerator.save_state` and `accelerator.load_state` for stateful training recovery. These cover prepared training components and RNG/scaler state supported by Accelerate. Register additional objects that expose `state_dict` and `load_state_dict` using `register_for_checkpointing` when their state is not already managed by `prepare`.

Store project-owned progress and best-metric state explicitly. Define the supported resume boundary, data-order strategy, and output/run identity; read [training organization](../training-organization/index.md#checkpoint-and-resume-contract) when changing this behavior.

`skip_first_batches` can skip consumed batches, but exact replay also requires restoring the data order and augmentation state for that boundary. Account for worker RNG and prefetch when claiming within-epoch equivalence.

For export/inference weights, follow the selected strategy's supported model-unwrapping, state-dict gathering, and saving APIs. Distributed/sharded strategies can require collective participation even when a single process writes the file.

## Verify the execution path

Use a small real dataset to verify a short training/evaluation run on the target device/strategy. For accumulation changes, check optimizer-step count and scheduler progress, including the final partial window. For recovery changes, compare uninterrupted and resumed progress, learning rate, metrics, and supported state under the project's deterministic conditions.

Exercise the actual distributed launch command when changing a distributed path. State the process count and strategy verified.

## Sources

- [Accelerate quick tour](https://huggingface.co/docs/accelerate/quicktour)
- [Accelerate gradient accumulation](https://huggingface.co/docs/accelerate/usage_guides/gradient_accumulation)
- [Accelerate checkpointing and custom state](https://huggingface.co/docs/accelerate/usage_guides/checkpoint)
- [Accelerate experiment trackers](https://huggingface.co/docs/accelerate/usage_guides/tracking)
