# LightningCLI

Read this file when the project uses or is adopting LightningCLI. Follow the documentation for the installed Lightning and jsonargparse versions.

## Configure and launch

LightningCLI supports YAML input and command-line overrides:

```bash
python main.py fit --print_config
python main.py fit --config config.yaml
python main.py fit --config config.yaml --trainer.max_epochs 100
```

These commands assume the project's `main.py` constructs `LightningCLI`; use its actual console command when packaged.

Use explicit model/data constructor parameters so the generated configuration exposes meaningful options. Use the documented `class_path` and `init_args` form when selecting component classes. Keep the training logic in the model/data components and the entry point focused on wiring.

## Save the effective configuration

By default, `SaveConfigCallback` saves the full YAML configuration to the log directory for each fit run. Keep this behavior or implement the project's equivalent deliberately. Saving configuration to a tracking backend can extend the callback's `save_config` method.

`save_config` runs on rank zero. Put operations requiring all ranks in an appropriate all-rank lifecycle hook. Keep collective operations out of rank-zero-only callbacks.

Keep configuration generation and file overwrite behavior consistent with run identity. When recovering, validate the stored experiment before enabling any overwrite. Use the CLI's checkpoint option for training recovery and confirm the installed CLI's exact option names with `--help`.

## Check the integration

Print a configuration, override a meaningful option, and run a short fit using it. Inspect the saved file in the actual logger directory. If model/data classes are selected dynamically, verify that the packaged command can import those classes from a supported working directory.

## Source

- [LightningCLI: YAML, overrides, automatic config saving, and callbacks](https://lightning.ai/docs/pytorch/stable/reference/cli/lightning_cli_advanced)
