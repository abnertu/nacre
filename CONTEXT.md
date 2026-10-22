# Composition model

Nacre evaluates machine policy into an immutable deployment containing the selected Home Manager generation. Arch adapters reconcile native state first; that exact home activates afterwards.

| Boundary | Owner | Contract |
| --- | --- | --- |
| Public policy | `lib/configuration-options.nix`, `modules/*/module.nix` | Typed options, defaults, assertions and native contributions |
| Role | `roles/` | `minimal` and `workstation` baselines at priority 1100 |
| Machine | A separate flake based on `templates/machine/` | Identity, existing login accounts, hardware, features and personal home modules |
| Platform | `platforms/arch/` | Native packages, files, accounts and privileged adapters |
| Home | `profiles/`, `modules/home/` | Shared user packages, static configuration and user services |
| Runtime preparation | Operator and feature preparation commands | Credentials, mutable data, native builds and model downloads |

`lib/mk-flake.nix` gives each machine fixed output names, including `#deployment`, `#nacre` and `lib.configuration`. Nacre applies it to `checks/fixtures`, which enables features without using a real machine's data.

`lib/eval-configuration.nix` combines the explicit feature registry, platform module and machine modules, validates cross-field assertions and normalizes the result. Feature modules contribute packages, groups and units through `arch`; `lib/mk-deployment.nix` passes the merged policy to the platform. Each resource has one owner.

Role definitions at priority 1100 yield to machine `lib.mkDefault` baselines at 1000; ordinary definitions override both. Import order does not establish precedence.

## Static policy and live convergence

Nix generates home files, units, drop-ins, routing and Caddy configuration. Native adapters handle ownership, safe file adoption, accounts, locks, pending markers, package operations, service state and recovery. Machine-owned adapters join through `arch.extensions`.

Home Manager projects static files into the home. Arch adapters copy or merge native files with native ownership. Prepared llama.cpp binaries and GGUF models stay outside the store.

Hyprland and Neovim use pinned inputs, machine-provided `sources.hyprland` / `sources.neovim`, or local worktrees selected by `development.hyprlandPath` / `development.neovimPath`. [Agent skills](docs/ai.md#agent-skills) are explicitly selected directories from pinned inputs and need no activation-time download.

## Deployment flow

1. Build the deployment and its embedded home generation.
2. Preflight core native state and optional-module readiness.
3. With `--update`, converge packages; then converge native files and services.
4. Converge ready optional modules.
5. Activate the embedded home.

Core failures stop immediately. An optional module may skip as `not ready` only before its preparation has ever completed. The Arch and home stages share no rollback transaction. See [deployment](docs/deployment.md) for recovery and [AI](docs/ai.md) for the separate preparation lifecycle.
