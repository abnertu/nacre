# Stop activation before Home Manager projects nvim or hypr into a Git
# worktree or over a leftover backup path.
{
  targets ? [
    "nvim"
    "hypr"
  ],
  activationName ? "checkExternalConfigTargets",
}:
{ config, lib, ... }:
{
  home.activation.${activationName} = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    (
      home_dir=${lib.escapeShellArg config.home.homeDirectory}
      config_home=${lib.escapeShellArg config.xdg.configHome}
      projection_targets=(${lib.escapeShellArgs targets})
      ${builtins.readFile ./check-projection.sh}
    )
  '';
}
