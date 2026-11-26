# Arch contributions of PowerPanel: package, configuration and service.
{ config, lib, ... }:
let
  enable = config.services.powerpanel.enable;
in
{
  options.services.powerpanel = import ./options.nix { inherit lib; };
  config.environment.etc."pwrstatd.conf" = lib.mkIf enable {
    text = import ./default.nix {
      inherit lib;
      config = config.services.powerpanel;
    };
    adopt = lib.mkOverride 1100 true;
  };
  # pwrstatd reads its configuration only when it starts.
  config.systemd.services.pwrstatd = lib.mkIf enable {
    restartTriggers = [ config.environment.etc."pwrstatd.conf".content ];
  };
  config.arch = {
    aur = lib.optional enable "powerpanel";
    groups = lib.optional enable "power";
  };
}
