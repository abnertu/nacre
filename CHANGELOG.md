# Changelog

## 0.1.0

First release under the Nacre name, after the project grew out of a personal Nix configuration.

- `nacre` command: `install`, `plan`, `switch`, `update`, `purge`, `status`, `generations`, `rollback`, and the AI, Runner and Noctalia operations.
- Roles: `minimal` and `workstation` baselines below host defaults.
- `nacre install` writes a configuration for a new machine; host-specific features are opt-in.
- `nix.settings` manages the Nix daemon settings in a block of `/etc/nix/nix.conf`; checkouts move from `~/.config/nix` to `~/.config/nacre`.
- Typed configuration evaluated into one deployment: Arch adapters converge native state, then the embedded Home Manager generation activates.
- Read-only `plan`, idempotent repeat runs, pending markers for interrupted work and a scoped `purge`.
- Hyprland desktop with Noctalia; application themes follow the wallpaper through Noctalia's templates.
- Optional local AI (llama.cpp behind llama-swap), virtualization, GitLab Runner, Personal Agent and Wi-Fi hotspot.
- CI: flake checks, a container deployment test and weekly input updates.
