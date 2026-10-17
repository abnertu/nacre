# AGENTS Instructions

Manage workstation changes in Nacre, `~/.config/nacre`. Read its `AGENTS.md` before
editing Arch policy, Home Manager configuration, desktop startup or Runners.
Other projects under this home directory own their own worktrees and rules.

- Use the normal configuration checkout; the home directory is not a Git
  worktree. Do not use the retired `dot` alias.
- Develop Hyprland and Neovim inputs outside runtime configuration paths.
  Adopt published revisions through intentional flake lock updates.
- Keep credentials, private keys, application databases and generated state
  outside configuration repositories and the Nix store.
- Validate source with builds and isolated tests. Activation, package managers,
  service changes and Runner operations require the relevant live state in scope.
- Do not add automatic cleanup, directory backups, garbage collection or Runner
  purge to workstation deployment.
