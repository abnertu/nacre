# nix-config

[![Check](https://img.shields.io/github/actions/workflow/status/gin31259461/nix-config/check.yml?branch=main&label=check&logo=githubactions&logoColor=white)](https://github.com/gin31259461/nix-config/actions/workflows/check.yml)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-1793D1?logo=archlinux&logoColor=white)](https://archlinux.org/)
[![Hyprland](https://img.shields.io/badge/Hyprland-58E1FF?logo=hyprland&logoColor=black)](https://hypr.land/)
[![Nix Flakes](https://img.shields.io/badge/Nix_Flakes-5277C3?logo=nixos&logoColor=white)](https://nixos.org/)
[![Home Manager](https://img.shields.io/badge/Home_Manager-26.05-5277C3?logo=nixos&logoColor=white)](https://nix-community.github.io/home-manager/)

Declarative Arch Linux + Hyprland workstation, managed with Nix and Home Manager.

Nix evaluates a typed configuration into one fixed deployment artifact. Arch adapters converge native files, packages and services, then the embedded Home Manager generation activates. Platform code lives under `platforms/`; Arch Linux (`x86_64-linux`) is the only platform today. This is not NixOS and not an installer.

![Desktop preview](docs/assets/preview.png)

## Features

- **Hyprland desktop** started by UWSM, with the Noctalia shell and one startup owner per application.
- **Typed configuration**: unknown options, wrong types and invalid combinations fail at evaluation.
- **Safe deployment**: preflight before any change; routine runs install nothing, only `update` syncs pacman and AUR.
- **Optional modules**: local AI (llama.cpp + llama-swap), virtualization, GitLab Runner, Personal Agent, Wi-Fi hotspot.
- **Secrets stay out**: credentials, keys and mutable data never enter Git or the Nix store.

## Requirements

- Arch Linux `x86_64` with the deployment user already created
- [Nix](https://nixos.org/download/) with flakes, and [just](https://just.systems/)

On a fresh Arch install without Nix, run the [bootstrap](docs/deployment.md#bootstrap) first.

## Quick start

```bash
git clone https://github.com/gin31259461/nix-config ~/.config/nix
cd ~/.config/nix
```

Edit [configuration.nix](configuration.nix) (defaults live in [hosts/arch](hosts/arch/default.nix)), then validate and build. None of these touch the system:

```bash
just check-fast   # format, types, lint, interfaces
just check        # all flake checks
just build        # build the deployment artifact
```

Read the [deployment guide](docs/deployment.md) before the first activation.

```bash
just arch-workstation plan      # show what would change
just arch-workstation           # converge Arch, then activate Home Manager
just arch-workstation update    # also upgrade declared pacman / AUR packages
just arch-workstation verbose   # full Nix, Home Manager and adapter diagnostics
just arch-workstation purge     # remove managed Arch state, skip Home Manager
```

`just --list` shows every recipe.

## Configuration

[configuration.nix](configuration.nix) is the single entry point. `hosts/` sets defaults with `lib.mkDefault`; plain definitions here override them.

```nix
networking.hotspot.enable = false;
users.users.abnertu.home.programs.git.settings.init.defaultBranch = "main";
```

Inspect a resolved value without activating:

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
```

See the [configuration guide](docs/configuration.md).

## Documentation

| Guide | Covers |
| --- | --- |
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

[CONTEXT.md](CONTEXT.md) explains the composition model.

## Development

Read [AGENTS.md](AGENTS.md) before changing code. Checks use temporary roots, fake native commands and isolated VMs; they never deploy. For deployment or adapter changes, `just container-test` deploys into a disposable podman container ([details](docs/deployment.md#container-test)).

CI on GitHub Actions:

- every push and PR: `nix flake check` and the deployment build
- deployment changes and weekly: the container deployment test
- weekly: a flake input update PR, plus Dependabot for workflow actions
