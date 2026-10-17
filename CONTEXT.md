# Composition model

This repository describes one existing Arch Linux workstation. Nix builds an immutable deployment artifact that embeds the selected Home Manager activation package. Arch adapters converge native files, packages and services, then that fixed generation activates.

| Boundary | Owner | Responsibility |
| --- | --- | --- |
| Public configuration | `configuration.nix`, `lib/configuration-options.nix`, feature modules in `modules/` | Typed options, defaults, assertions, native contributions |
| Role | `roles/` | Baseline composition (`minimal`, `workstation`) below host defaults |
| Host | `hosts/` | Identity, users, hardware and feature baselines |
| Native platform | `platforms/arch/` | Arch packages, generated configuration, privileged convergence |
| Home | `profiles/`, `homes/`, home modules | User packages, static files, user services |
| External runtime | The operator and per-feature preparation commands | Secrets, mutable data, native builds, model downloads |

`configuration.nix` imports a host. Role baselines use priority 1100 and host baselines `lib.mkDefault` (1000), so hosts refine roles and plain definitions win regardless of import order. `lib/eval-configuration.nix` evaluates the explicit feature registry (`modules/default.nix`) with the platform module, checks cross-field assertions and normalizes the result. Feature modules contribute native packages, groups and units to the internal `arch` option, which `lib/mk-deployment.nix` hands to the Arch platform. Every package, account, file and service has one owner.

## Static policy and live convergence

Nix generates fixed content: Home Manager files, systemd units, drop-ins, AI routing and Caddy configuration. Native adapters handle what depends on live machine state: adopting existing files safely, ownership and permission checks, accounts, service state, locks, pending markers, package operations and failure reporting. GitLab Runner instances are per-environment TOML files that a pinned `runnerctl` validates and renders; tokens merge only at runtime and never enter a derivation.

Upstream agent skills are pinned flake inputs. The AI module selects them explicitly and Home Manager projects whole skill directories; only custom skills live here. See [agent skills](docs/ai.md#agent-skills).

Home Manager links static home files into the store. Arch native files are copied or merged into `/etc` with native ownership. Prepared llama.cpp binaries and GGUF models stay outside the store. Hyprland and Neovim sources are pinned flake inputs, or local worktrees projected with out-of-store symlinks through `development.hyprlandPath` / `development.neovimPath`.

## Deployment flow

1. Build the deployment artifact and its fixed Home Manager generation.
2. Preflight Arch identity, packages, core native state and optional module readiness.
3. With `--update` only, converge packages; then converge native files and services.
4. Converge optional modules that are ready.
5. Activate the home generation.

Core failures stop the run. An optional module may report `not ready` only if its preparation never completed. Arch and Home Manager share no rollback. See [deployment](docs/deployment.md) for purge and recovery, [AI](docs/ai.md) and [Runners](docs/runners.md) for their separate lifecycles.
