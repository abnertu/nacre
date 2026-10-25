# Nacre

Declarative configuration and deployment for existing Arch Linux and Hyprland machines, evaluated with Nix.

[![check](https://github.com/abnertu/nacre/actions/workflows/check.yml/badge.svg?branch=main)](https://github.com/abnertu/nacre/actions/workflows/check.yml)
[![Release](https://img.shields.io/github/v/release/abnertu/nacre)](https://github.com/abnertu/nacre/releases/latest)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-1793D1?logo=archlinux&logoColor=white)](https://archlinux.org/)
[![Nix](https://img.shields.io/badge/Nix-5277C3?logo=nixos&logoColor=white)](https://nixos.org/)

Nix validates typed options and builds a fixed deployment artifact. Arch adapters converge native files, packages and services. Then the artifact's Home Manager generation activates. Machines keep their own flakes and follow Nacre as an input. Credentials and mutable application data stay outside Git and the Nix store.

![Desktop preview](docs/assets/preview.png)

## Install

Start from Arch Linux `x86_64` with network access and an existing login account in `wheel`. Nacre does not install the base operating system.

Read [the bootstrap script](scripts/bootstrap.sh). Then run:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
```

The script enables `[multilib]` and installs the prerequisites, including Nix and yay. Then it offers to run `nacre install`. Installation creates a machine flake at `~/.config/nacre`, shows a preview of the changes and asks before it deploys. See [installation](docs/install.md) for unattended setup and for the restore of an existing flake.

## Usage

```bash
nacre plan       # preview changes
nacre switch     # converge Arch and activate the built home
nacre update     # also upgrade declared pacman and AUR packages
nacre doctor     # report drift and pending work
```

A routine `switch` installs no packages. To update Nacre itself, in the machine checkout:

1. Run `nix flake update nacre`.
2. Review the lock diff and the output of `nacre plan`.
3. Run `nacre switch`.

## Configuration

The machine's `configuration.nix` selects a `minimal` or `workstation` role and overrides its baseline:

```nix
role = "workstation";
networking.firewall.enable = false;
users.users.alice.home.programs.git.settings.init.defaultBranch = "main";
```

The workstation role adds Hyprland through UWSM, Noctalia and shared desktop configuration. Optional features include local AI, virtualization, a NetworkManager hotspot and machine-owned adapters. The [fixture machine](checks/fixtures/configuration.nix) demonstrates the full configuration.

| Guide | Use it for |
| --- | --- |
| [Install](docs/install.md) | Bootstrap and create a machine flake |
| [Configuration](docs/configuration.md) | Roles, options, users and extensions |
| [Deployment](docs/deployment.md) | Commands, diagnostics, migration and recovery |
| [System settings](docs/system-settings.md) | Native ownership and pending changes |
| [Desktop session](docs/desktop-session.md) | Startup, themes and local development |
| [Noctalia](docs/noctalia-config.md) | Review, capture and deploy UI preferences |
| [Hotspot](docs/hotspot.md) | Adopt an existing AP connection |
| [Local AI](docs/ai.md) | Prepare models and serve loopback APIs |
| [Backup](docs/backup.md) | Preserve state outside the flake |

[CONTEXT.md](CONTEXT.md) explains composition. [CHANGELOG.md](CHANGELOG.md) records releases.
