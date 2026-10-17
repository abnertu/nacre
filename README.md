# Nacre

[![Check](https://img.shields.io/github/actions/workflow/status/gin31259461/nacre/check.yml?branch=main&label=check&logo=githubactions&logoColor=white)](https://github.com/gin31259461/nacre/actions/workflows/check.yml)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-1793D1?logo=archlinux&logoColor=white)](https://archlinux.org/)
[![Hyprland](https://img.shields.io/badge/Hyprland-58E1FF?logo=hyprland&logoColor=black)](https://hypr.land/)
[![Nix Flakes](https://img.shields.io/badge/Nix_Flakes-5277C3?logo=nixos&logoColor=white)](https://nixos.org/)
[![Home Manager](https://img.shields.io/badge/Home_Manager-26.05-5277C3?logo=nixos&logoColor=white)](https://nix-community.github.io/home-manager/)

Declarative Arch Linux + Hyprland, layered with Nix.

Nacre, mother-of-pearl, builds up in layers on the shell beneath it. Likewise this project layers a typed, reproducible configuration onto an existing Arch Linux install instead of replacing it.

Nix evaluates a typed configuration into one fixed deployment artifact. Arch adapters converge native files, packages and services, then the embedded Home Manager generation activates. Platform code lives under `platforms/`; Arch Linux (`x86_64-linux`) is the only platform today. It is not NixOS: the base system stays Arch.

![Desktop preview](docs/assets/preview.png)

## Features

- **One command**: `nacre` installs a machine, previews and applies changes, reports status and rolls back home generations.
- **Roles**: a `minimal` or `workstation` baseline that hosts and your configuration refine.
- **Hyprland desktop** started by UWSM, with the Noctalia shell and one startup owner per application.
- **Typed configuration**: unknown options, wrong types and invalid combinations fail at evaluation.
- **Safe deployment**: preflight before any change; routine runs install nothing, only `update` syncs pacman and AUR.
- **Optional modules**: local AI (llama.cpp + llama-swap), virtualization, GitLab Runner, Personal Agent, Wi-Fi hotspot.
- **Secrets stay out**: credentials, keys and mutable data never enter Git or the Nix store.

## Requirements

- Arch Linux `x86_64`, with your account in `wheel`
- network access; the bootstrap installs Nix ([just](https://just.systems/) is only for development)

## Quick start

On a new machine ([install guide](docs/install.md)):

```bash
git clone https://github.com/gin31259461/nacre ~/.config/nacre
cd ~/.config/nacre
./scripts/bootstrap.sh
nix run .#nacre -- install
```

Afterwards, day to day ([deployment guide](docs/deployment.md)):

```bash
nacre check               # every flake check; touches nothing
nacre build               # build the deployment artifact; touches nothing
nacre plan                # show what would change
nacre switch              # converge Arch, then activate Home Manager
nacre update              # also upgrade declared pacman / AUR packages
nacre --verbose switch    # full Nix, Home Manager and adapter diagnostics
nacre purge               # remove managed Arch state, skip Home Manager
```

`nacre --help` lists every command, including `status`, `generations`, `rollback` and the AI, Runner and Noctalia operations.

## Configuration

[configuration.nix](configuration.nix) is the single entry point. A role sets the baseline, a host can refine it with `lib.mkDefault`, and plain definitions in `configuration.nix` win. This repository's own machine is [hosts/arch](hosts/arch/default.nix), a full example of a host.

```nix
role = "workstation";
networking.firewall.enable = false;
users.users.alice.home.programs.git.settings.init.defaultBranch = "main";
```

Inspect a resolved value without activating:

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
```

See the [configuration guide](docs/configuration.md).

## Documentation

| Guide | Covers |
| --- | --- |
| [Install](docs/install.md) | From a fresh Arch install to the first deployment |
| [Deployment](docs/deployment.md) | Bootstrap, activation, updates, purge, recovery |
| [Configuration](docs/configuration.md) | Options, precedence, resolved values |
| [System settings](docs/system-settings.md) | Native file ownership, preflight, pending markers |
| [Desktop session](docs/desktop-session.md) | UWSM, startup ownership, live development |
| [Noctalia config](docs/noctalia-config.md) | Capturing and deploying reviewed UI preferences |
| [Hotspot](docs/hotspot.md) | Adopting an existing NetworkManager AP |
| [Local AI](docs/ai.md) | Model preparation, loopback services, agent skills ([benchmarks](docs/ai-benchmarks.md)) |
| [GitLab Runner](docs/runners.md) | Separate reconcile, registration and verification |
| [Personal Agent](docs/personal-agent.md) | External runtime config and the native service |
| [Backup](docs/backup.md) | State outside the repository and restore order |

[CONTEXT.md](CONTEXT.md) explains the composition model; [CHANGELOG.md](CHANGELOG.md) lists releases.

## Development

Read [AGENTS.md](AGENTS.md) before changing code. Checks use temporary roots, fake native commands and isolated VMs; they never deploy. For deployment or adapter changes, `just container-test` deploys into a disposable podman container ([details](docs/deployment.md#container-test)).

CI on GitHub Actions:

- every push and PR: `nix flake check` and the deployment build
- deployment changes and weekly: the container deployment test
- weekly: a flake input update PR, plus Dependabot for workflow actions
