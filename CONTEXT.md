# Composition model

Nacre layers a typed configuration onto an existing Arch Linux install. Nix builds an immutable deployment artifact that embeds the selected Home Manager activation package. Arch adapters converge native files, packages and services, then that fixed generation activates.

| Boundary | Owner | Responsibility |
| --- | --- | --- |
| Public configuration | `lib/configuration-options.nix`, feature modules in `modules/` | Typed options, defaults, assertions, native contributions |
| Role | `roles/` | Baseline composition (`minimal`, `workstation`) below machine defaults |
| Machine | A machine flake (`templates/machine/`) | Identity, users, hardware, feature choices, personal home modules and dotfiles |
| Native platform | `platforms/arch/` | Arch packages, generated configuration, privileged convergence |
| Home | `profiles/`, `modules/home/` | Shared user packages, static files, user services |
| External runtime | The operator and per-feature preparation commands | Secrets, mutable data, native builds, model downloads |

`lib/mk-flake.nix` turns a machine's modules into its flake outputs under fixed names (`#deployment`, `#nacre`, `lib.configuration`), so machine flakes follow Nacre as an input and one `nacre` command serves all of them. Nacre's own flake applies it to the fixture machine in `checks/fixtures`. Role baselines use priority 1100 and machine baselines `lib.mkDefault` (1000), so machines refine roles and plain definitions win regardless of import order. `lib/eval-configuration.nix` evaluates the explicit feature registry (`modules/default.nix`) with the platform module, checks cross-field assertions and normalizes the result. Feature modules contribute native packages, groups and units to the internal `arch` option, which `lib/mk-deployment.nix` hands to the Arch platform. Every package, account, file and service has one owner.

## Static policy and live convergence

Nix generates fixed content: Home Manager files, systemd units, drop-ins, AI routing and Caddy configuration. Native adapters handle what depends on live machine state: adopting existing files safely, ownership and permission checks, accounts, service state, locks, pending markers, package operations and failure reporting. A machine flake adds adapters of its own through `arch.extensions`; arch-switch runs them like the built-in optional modules.

Upstream agent skills are pinned flake inputs. The AI module selects them explicitly and Home Manager projects whole skill directories. See [agent skills](docs/ai.md#agent-skills).

Home Manager links static home files into the store. Arch native files are copied or merged into `/etc` with native ownership. Prepared llama.cpp binaries and GGUF models stay outside the store. Hyprland and Neovim sources are pinned flake inputs, a machine's own inputs through `sources.hyprland` / `sources.neovim`, or local worktrees projected with out-of-store symlinks through `development.hyprlandPath` / `development.neovimPath`.

## Deployment flow

1. Build the deployment artifact and its fixed Home Manager generation.
2. Preflight Arch identity, packages, core native state and optional module readiness.
3. With `--update` only, converge packages; then converge native files and services.
4. Converge optional modules that are ready.
5. Activate the home generation.

Core failures stop the run. An optional module may report `not ready` only if its preparation never completed. Arch and Home Manager share no rollback. See [deployment](docs/deployment.md) for purge and recovery, [AI](docs/ai.md) for its separate lifecycle.
