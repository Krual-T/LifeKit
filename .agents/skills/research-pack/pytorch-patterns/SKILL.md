---
name: pytorch-patterns
description: PyTorch modeling and training engineering patterns for maintainable, efficient, reproducible projects. Use when writing or reviewing PyTorch models, data pipelines, training loops, project structure, experiment configuration, logging, or checkpoint recovery.
metadata:
  origin: ECC
---

# PyTorch Development Patterns

Improve the part of the training project requested by the user. Use the routes below to load relevant guidance while keeping the project's existing framework and conventions in view.

## Route before reading

Inspect the target module and applicable project instructions first. Read the package, training entry point, configuration, and logger when the task depends on them. Match the task to the routes below and read only the references needed for that task. Follow secondary links when the selected framework or backend requires them.

| Task or symptom | Read first |
| --- | --- |
| Implement or review an `nn.Module`, Dataset, tensor shapes, device handling, AMP, or performance | [Core PyTorch patterns](references/pytorch-core.md) |
| Organize directories, separate reusable code from experiments, or define data and artifact locations | [Project structure](references/project-structure/index.md) |
| Organize training/validation/data responsibilities, use Lightning, or repair checkpoint/resume behavior | [Training organization](references/training-organization/index.md) |
| Manage YAML/CLI options, model/scenario combinations, config snapshots, LightningCLI, or Hydra | [Configuration](references/configuration/index.md) |
| Record curves/images, compare runs, preserve log continuity, or use TensorBoard/CSV/MLflow | [Experiment tracking](references/experiment-tracking/index.md) |
| Keep a custom training loop while adding mixed precision, distributed execution, accumulation, or Accelerate | [Custom training](references/custom-training/index.md) |

For a broad training-engineering review, read the five domain entry points, then load framework-specific details where applicable. For a focused change, select the relevant route directly. Combine routes when behavior crosses boundaries: resume usually touches training, configuration, and tracking; a dataset contract change can also touch structure and core patterns.

## Shared working rules

- Preserve an existing framework and logger unless the task calls for migration. Choose LightningCLI or Hydra for the actual configuration needs; choose Lightning or an explicit loop for training ownership.
- Keep network/inference code reusable. Make configuration, data identity, selection metrics, state ownership, and artifact paths explicit at the training boundary.
- Distinguish a new run, initialization from weights, and continuation of an existing run. Validate compatibility before changing an existing run's files.
- Record seeds and environment details. State the supported resume boundary and deterministic conditions; seed initialization alone does not establish replay equivalence.
- Use the installed library versions and their official documentation. Benchmark performance changes on the relevant workload.
- Verify changed behavior with proportionate checks: a short run for a training path, interruption/resume for recovery changes, and metric/log continuity for tracking changes. Report what actually ran.

When reviewing, connect each finding to a file, trigger, consequence, and focused correction. When implementing, explain changed behavior, relevant verification, and remaining limits.

## Provenance

Derived from [ECC's pytorch-patterns](https://github.com/affaan-m/ECC/tree/b38be6a7f6350964d59328b52f0624e1d1d552d1/skills/pytorch-patterns), under the [MIT license](LICENSE). The domain references summarize the official sources linked in each file; they are maintained guidance for this fork.
