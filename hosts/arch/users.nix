{ config, lib }:
{
  abnertu = {
    description = lib.mkDefault "Abner Tu";
    homeDirectory = lib.mkDefault "/home/abnertu";
    stateVersion = lib.mkDefault "26.05";
    admin = lib.mkDefault true;
    groups = lib.mkDefault (
      [
        "i2c"
        "realtime"
      ]
      ++ lib.optional (config.hardware.openrazer.enable && config.desktop.enable) "openrazer"
    );
    homeModules = lib.mkDefault [
      ../../homes/abnertu/home.nix
      ../../homes/abnertu/dotfiles.nix
    ];
  };
}
