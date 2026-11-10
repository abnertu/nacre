# Changelog

## 0.10.0 (2026-11-10)

### Features

- **deployment**: Support opt-in extension purge hooks
- **runner**: Integrate native deployment and configured operator commands (breaking)

## 0.9.0 (2026-11-06)

### Features

- **ai**: Restore configurable built-in agent skills (breaking)

### Documentation

- **ai**: Explain built-in skill selection and migration

## 0.8.1 (2026-11-06)

### Refactoring

- **desktop**: Adopt the rewritten Hyprland configuration

## 0.8.0 (2026-11-06)

### Features

- **ai**: Take agent skill sets from the machine flake (breaking)

### Fixes

- **ai**: Make the benchmark tests independent of process timing

### Refactoring

- Adopt nix-adapter v0.7.0 (breaking)
- **options**: Declare every option explicitly and describe it
- **cli**: Split the nacre command into a package by concern
- **switch**: Name the deployment stages and document every step
- **adapters**: Split core and system convergence by resource
- **ai**: Split AI preflight, convergence and preparation into steps
- **ai**: Split the benchmark into its parser, monitor and matrix
- **noctalia**: Split the sync command's entry point and deploy

### Documentation

- **nix**: State what each Nix file owns in a header comment
- Clarify ownership and rewrite the operator guides

## 0.7.0 (2026-11-05)

### Features

- **ai**: Bound model memory and own measured runtime defaults (breaking)
- **ai**: Install gh and project the gh and abnertu skill sets

### Refactoring

- **checks**: Exercise native ownership and session behavior

### Documentation

- Tighten the README, agent rules and deployment guide
- **readme**: Fix CI and release badges
- **readme**: Align the Check badge with Hypr
- Simplify the check badge label
- Drop the license badge and section, add a Nix badge and index guides
- Rewrite README and AGENTS.md to ASD-STE100 writing rules
- Rewrite the guides to ASD-STE100 writing rules
- Align writing rules with documentation skill 0.4.1

## 0.6.2 (2026-10-21)

### Features

- **ai**: Install kepano's Obsidian skills

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

First Nacre release, extracted from the personal Nix configuration.

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
