# Project Structure

Use this guide when creating or reorganizing a training repository. Start from the existing import package and execution paths; retain useful project conventions.

## Separate source, configuration, data, and results

Use these responsibilities to adapt a directory layout:

```text
pyproject.toml              # Package, dependencies, and development tools
<dependency lockfile>      # Environment resolved by the chosen package manager
src/<package>/
  data/                    # Datasets, transforms, split readers, data modules
  models/                  # Networks, losses, and task metrics
  training/                # Training systems, callbacks, and run lifecycle
  train.py                 # Thin training entry point
  evaluate.py              # Evaluation using explicit data and checkpoints
configs/                   # Versioned configuration, if the project uses it
scripts/                   # Thin data preparation and operational entry points
tests/                     # Tests of meaningful data and training contracts
notebooks/                 # Exploration and analysis importing reusable code
data/                      # Local datasets or pointers to managed storage
outputs/                   # Per-run configs, logs, checkpoints, and predictions
reports/                   # Analysis and figures intended for review
```

This is an adaptable example. Cookiecutter Data Science uses its own package and `modeling/` layout; use its separation of responsibilities where it fits. Keep `raw`, `interim`, `processed`, and `external` distinctions when the data pipeline needs them. Treat raw inputs as immutable and write derived data to a separate destination.

Keep dataset downloads, weights, caches, and run outputs outside source control according to project policy. Version the code, configuration, environment specification, and appropriate dataset release IDs or split manifests. External storage can provide the data directories' role without duplicating a dataset locally.

## Keep experiments importable

- Put maintained models, datasets, metrics, and training logic in the package. Let experiments select them through configuration or thin launchers.
- Keep notebooks for exploration, inspection, and reporting. Move logic required by repeated training into importable modules.
- Give an experiment directory a clear purpose: configuration and analysis, or an explicitly frozen historical snapshot. Locate the maintained implementation once.
- Use explicit dependencies or configuration to select behavior. Pass a dataset factory, transform, or component directly when variation is needed.
- Resolve package resources and data roots explicitly. Check the documented launch command from the working directories the project supports.

## Preserve the public entry points during reorganization

Before moving files, find their callers: console scripts, shell launchers, notebooks, tests, evaluation, and export. Update imports and configuration targets together. Retain a small compatibility entry point when existing users need it, and have it call the maintained implementation.

Keep the project's existing package manager and lockfile. Configure Ruff, pytest, and other tools in the project's established location when those tools are adopted. Choose development tooling for a concrete need.

## Verify the changed boundary

For a file move, verify package import and the affected documented command. For a moved training path, run a short end-to-end training/evaluation cycle using a small dataset. Check that run outputs appear in the configured location and that evaluation/export can consume the resulting checkpoint.

## Sources

- [Cookiecutter Data Science v2: options and directory structure](https://cookiecutter-data-science.drivendata.org/)
- [Cookiecutter Data Science: data, reproducibility, and project conventions](https://cookiecutter-data-science.drivendata.org/opinions/)
