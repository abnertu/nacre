{ config, lib, ... }:
let
  enable = config.services.powerpanel.enable;
in
{
  options.services.powerpanel = import ./options.nix { inherit lib; };
  config.arch = {
    aur = lib.optional enable "powerpanel";
    groups = lib.optional enable "power";
    systemUnits = lib.optional enable "pwrstatd.service";
  };
}
