# Changelog

## 0.6.1 (2026-10-19)

### Fixes

- **noctalia-config**: Deploy with nacre's input overrides and checkout

### Refactoring

- **profiles**: Tidy the shell, Git and package baselines

## 0.6.0 (2026-10-19)

### Features

- **home**: Ship default tool configurations and make Ghostty the terminal (breaking)
- **arch**: Let machine flakes add adapters; drop Personal Agent and GitLab Runner (breaking)
- **bootstrap**: Run from curl and continue into nacre install

## 0.5.0 (2026-10-19)

### Features

- **config**: Let machines add packages and config sources (breaking)
- **cli**: Pass --override-input to every Nix evaluation

### Fixes

- **system**: Converge UTC on a machine without /etc/localtime

### Refactoring

- **ai**: Remove Antigravity and the Obsidian vault skill (breaking)
- **home**: Move personal dotfiles out of the workstation profile (breaking)
- Remove the maintainer's machine from Nacre (breaking)

## 0.4.0 (2026-10-18)

### Features

- **cli**: Add bash and zsh completions

## 0.3.0 (2026-10-18)

### Features

- **arch**: Hold packages at their installed version during update
- **cli**: Report doctor's findings after every update
- **home**: Start new user units on activation
- **home**: Declare fcitx5 settings read-only
- **noctalia-config**: Report uncaptured GUI changes in doctor

### Refactoring

- **desktop**: Remove the unused top-level Quickshell configuration

### Documentation

- **backup**: Cover fcitx5 learning and uncaptured Noctalia changes

## 0.2.0 (2026-10-18)

### Features

- **cli**: Add doctor and changes

### Fixes

- **desktop**: Stop Kitty from opening every window maximized
- **cli**: Find the installing account without USER

### Refactoring

- Drop the transitional nix.conf (breaking)

## 0.1.0

First release under the Nacre name, after the project grew out of a personal Nix configuration.

- Machine flakes: `nacre.lib.mkFlake { modules = [ ./configuration.nix ]; }`. Each machine follows Nacre as an input and upgrades with `nix flake update nacre`.
- `nacre` command: `install` (creates the machine flake), `plan`, `switch`, `update`, `purge`, `status`, `generations`, `rollback`, and the AI, Runner and Noctalia operations.
- `nacre plan` previews every adapter's files, units, restarts and runtime changes, judged as convergence judges them.
- Roles: `minimal` and `workstation` baselines below host defaults; host-specific features are opt-in.
- Typed configuration evaluated into one deployment: Arch adapters converge native state, then the embedded Home Manager generation activates.
- Python orchestration and adapters, pyright strict, with every adapter manifest declared as a `TypedDict` and checked against what Nix generates.
- Read-only `plan`, idempotent repeat runs, pending markers for interrupted work and a scoped `purge`.
- `update` resolves the inventory against the full upgrade it performs and reports pacman's dependency conflicts.
- `nix.settings` manages the Nix daemon settings in a block of `/etc/nix/nix.conf`; checkouts live at `~/.config/nacre`.
- Hyprland desktop with Noctalia; application themes, including running Kitty windows, follow the wallpaper.
- Optional local AI (llama.cpp behind llama-swap), Claude Code and Claude Desktop with pinned agent skills, virtualization, GitLab Runner, Personal Agent and Wi-Fi hotspot.
- CI: flake checks, a container deployment test and weekly input updates.
