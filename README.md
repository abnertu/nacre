# Nacre

Declarative Arch Linux + Hyprland machines, layered with Nix.

[![Check](https://img.shields.io/github/actions/workflow/status/abnertu/nacre/check.yml?branch=main&label=check&logo=githubactions&logoColor=white)](https://github.com/abnertu/nacre/actions/workflows/check.yml)
[![Release](https://img.shields.io/github/v/release/abnertu/nacre)](https://github.com/abnertu/nacre/releases/latest)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-x86__64-1793D1?logo=archlinux&logoColor=white)](https://archlinux.org/)

Nacre keeps an existing Arch install and adds a typed Nix configuration on top; it is not NixOS. Nix evaluates the configuration into one fixed deployment artifact. Arch adapters converge native files, packages and services, then the Home Manager generation embedded in that artifact activates. Unknown options, wrong types and invalid combinations fail at evaluation, before anything changes.

It manages:

- a `minimal` or `workstation` role: the workstation adds a Hyprland session started by UWSM with the Noctalia shell
- native system settings: locale, time, firewall, hostname, journald, logind, TRIM, a NetworkManager hotspot, a CyberPower UPS
- optional local AI (llama.cpp behind llama-swap, loopback only), virtualization and [extensions](docs/configuration.md#machine-extensions) a machine adds
- the home through Home Manager, with shared profiles and your own modules

Credentials, keys and mutable application data never enter Git or the Nix store.

![Desktop preview](docs/assets/preview.png)

## Requirements

- Arch Linux `x86_64`, with your account in `wheel`
- network access; the bootstrap installs Nix

## Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
```

The bootstrap changes the host: it enables `[multilib]` and installs the base packages, Nix and yay. Read it first. It then offers to run `nacre install`. That command writes your machine's own flake to `~/.config/nacre`, which follows Nacre as an input, then plans and deploys it. The [install guide](docs/install.md) covers unattended installs and restoring an existing machine.

## Usage

```bash
nacre plan        # show what would change; touches nothing
nacre switch      # converge Arch, then activate Home Manager
nacre update      # switch, also upgrading declared pacman and AUR packages
nacre doctor      # report what needs attention; touches nothing
```

Routine `switch` runs install nothing; only `update` touches pacman and AUR. `nacre --help` lists every command. To upgrade Nacre itself, run `nix flake update nacre` in `~/.config/nacre`, review `nacre plan`, then switch.

## Configuration

A machine's `configuration.nix` is its entry point. The role sets the baseline, imported machine files can refine it with `lib.mkDefault`, and plain definitions win regardless of import order:

```nix
role = "workstation";
networking.firewall.enable = false;
users.users.alice.home.programs.git.settings.init.defaultBranch = "main";
```

The [fixture machine](checks/fixtures/configuration.nix) enables every feature.

## Documentation

| Guide | Covers |
| --- | --- |
| [Install](docs/install.md) | From a fresh Arch install to the first deployment |
| [Deployment](docs/deployment.md) | Commands, updates, purge, diagnostics, recovery |
| [Configuration](docs/configuration.md) | Roles, options, homes, machine extensions |
| [System settings](docs/system-settings.md) | Native file ownership, preflight, pending markers |
| [Desktop session](docs/desktop-session.md) | UWSM, startup ownership, themes, live development |
| [Noctalia config](docs/noctalia-config.md) | Capturing and deploying reviewed UI preferences |
| [Hotspot](docs/hotspot.md) | Adopting an existing NetworkManager AP |
| [Local AI](docs/ai.md) | Models, preparation, loopback services, agent skills |
| [Backup](docs/backup.md) | State outside the repository and restore order |

[CONTEXT.md](CONTEXT.md) explains the composition model; [CHANGELOG.md](CHANGELOG.md) lists releases.

## License

[GPL-3.0-or-later](LICENSE).
