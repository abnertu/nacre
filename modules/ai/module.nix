# The programs.ai options and the AUR packages of the enabled AI tools.
{ config, lib, ... }:
let
  cfg = config.programs.ai;
  packages = import ./packages.nix;
in
{
  imports = [
    (import ./skill-aliases.nix {
      prefix = [
        "programs"
        "ai"
      ];
    })
  ];
  options.programs.ai = import ./options.nix { inherit lib; };
  config.arch.inventory = {
    codex = {
      enable = cfg.enable && cfg.codex.enable;
      aur.required = packages.codex;
    };
    claude = {
      enable = cfg.enable && cfg.claude.enable;
      aur.required = packages.claude;
    };
    claude-desktop = {
      enable = cfg.enable && cfg.claudeDesktop.enable && config.desktop.enable;
      aur.required = packages.claudeDesktop;
    };
  };
}
