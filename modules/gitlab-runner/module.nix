{ config, lib, ... }:
let
  cfg = config.services.gitlabRunner;
in
{
  options.services.gitlabRunner = import ./options.nix { inherit lib; };
  config.arch.pacman = lib.optionals (cfg.enable && cfg.configFiles != [ ]) (import ./packages.nix);
}
