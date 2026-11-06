# Hydra

Read this file when the project uses Hydra or needs configuration groups and experiment combinations. Use the installed Hydra/OmegaConf versions and their corresponding documentation.

## Compose named components

Group settings around replaceable responsibilities such as `data`, `model`, `trainer`, `callbacks`, `logger`, and `experiment`. Use experiment configurations to select components and meaningful overrides. Keep the defaults order and `_self_` position intentional: they affect which values win.

Hydra's `version_base` selects compatibility behavior. It is separate from the installed `hydra-core` package version; record and test both when upgrading.

When using `_target_` with `hydra.utils.instantiate`, keep targets within the application's intended component contract and inspect the constructed dependencies. Configuration-driven construction executes application code.

## Make path behavior deliberate

Hydra creates a run output directory containing logs and configuration snapshots, including `.hydra/config.yaml`, `.hydra/hydra.yaml`, and `.hydra/overrides.yaml` under the standard configuration.

With Hydra 1.2+ compatibility defaults, `hydra.job.chdir` is false. Set the desired behavior explicitly for a project and resolve dataset/artifact paths accordingly. When changing the working directory, use the documented original-working-directory/path helpers where needed.

Make the entry point's config search path work after package installation. If YAML is packaged as application data, include it in the built distribution. Check the real console script from a supported directory, including outside the source checkout when that is part of the contract.

## Keep snapshots and recovery consistent

Save the composed application configuration and relevant overrides used by training. Keep dataset identity and runtime-derived behavior in run metadata when they are outside the configuration snapshot.

A resume invocation may itself receive a fresh Hydra output directory. Explicitly identify the training run being continued and keep checkpoint, metrics, and run metadata associated with that run. Validate its original experiment before writing to it.

Check the official release notes when changing Hydra versions, then verify composition, paths, entry-point packaging, and recovery against the project's installed stack.

## Sources

- [Hydra configuration groups](https://hydra.cc/docs/1.3/tutorials/basic/your_first_app/config_groups/)
- [Hydra defaults list and composition order](https://hydra.cc/docs/1.3/advanced/defaults_list/)
- [Hydra working directory and saved configuration](https://hydra.cc/docs/1.3/tutorials/basic/running_your_app/working_directory/)
- [Hydra version_base](https://hydra.cc/docs/1.3/upgrades/version_base/)
- [Hydra releases](https://github.com/hydra-ecosystem/hydra/releases)
