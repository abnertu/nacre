{ config, lib, ... }:
let
  cfg = config.programs.ai;
  packages = import ./packages.nix;
in
{
  options.programs.ai = import ./options.nix { inherit lib; };
  config.arch.aur =
    lib.optionals (cfg.enable && cfg.codex.enable) packages.codex
    ++ lib.optionals (
      cfg.enable && cfg.agy.enable && cfg.agy.pkg.enable && cfg.agy.package.enable
    ) packages.agy
    ++ lib.optionals (cfg.enable && cfg.claude.enable) packages.claude
    ++ lib.optionals (
      cfg.enable && cfg.claudeDesktop.enable && config.desktop.enable
    ) packages.claudeDesktop;
}
