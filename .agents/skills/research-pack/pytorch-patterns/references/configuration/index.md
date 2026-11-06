# Configuration

Use this guide for experiment options, configuration composition, and recording the effective configuration.

## Select the existing configuration path

Inspect the training entry point and installed packages first. Keep one clear owner of argument parsing and object construction.

| Project situation | Read next |
| --- | --- |
| Lightning project using LightningCLI, or a new Lightning entry point with straightforward YAML/CLI requirements | [LightningCLI](lightning-cli.md) |
| Project already using Hydra, or requiring named combinations of data, models, scenes, trainers, and experiments | [Hydra](hydra.md) |
| Existing argparse, dataclass, or another working configuration system | Apply the common contract below in that system |

Use the configuration system the task calls for. Introduce or migrate a tool when its composition, validation, or lifecycle behavior addresses a project requirement.

## Common configuration contract

- Make the configuration that actually drives execution inspectable: defaults, overrides, resolved values, and any runtime adjustment that changes behavior.
- Give paths explicit meaning. Distinguish data roots, initial weights, recovery checkpoints, and the current run's artifact directory.
- Validate incompatible settings, dataset/split identity, and recovery conditions before changing an existing run's files.
- Keep secrets in the established secret mechanism. Save a shareable configuration with sensitive values omitted or redacted.
- Record the source revision, environment specification, split manifest or managed dataset release ID, and metric-selection policy alongside the configuration where the project needs them.
- Keep new-run, weight-initialization, and resume options explicit. A populated output directory should require an intentional continuation or a new destination.

A saved YAML file captures configuration. Data availability, external code, package versions, and project-owned training state are additional parts of reproducing an experiment.

## Verify configuration behavior

Inspect the effective configuration using the selected tool's supported print/compose command. Exercise a representative override, the supported working directory, and the installed entry point. Check the saved configuration against the values used by training. For resume changes, confirm that a rejected configuration leaves the existing run intact.
