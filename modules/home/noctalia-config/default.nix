{
  config,
  lib,
  pkgs,
  hostName,
  inputs,
  ...
}:
{
  options.workstation.noctalia.preferencesFile = lib.mkOption {
    type = lib.types.nullOr lib.types.path;
    default = null;
    description = "Reviewed, non-secret Noctalia user preferences in the repository; null leaves Noctalia's own settings.";
  };
  config = lib.mkIf (config.workstation.capabilities.noctalia-config.enable or true) {
    xdg.configFile."noctalia/config.toml" =
      lib.mkIf (config.workstation.noctalia.preferencesFile != null)
        {
          source = config.workstation.noctalia.preferencesFile;
        };
    home.packages = [
      (import ./package.nix {
        inherit pkgs;
        adapterPython = inputs.nix-adapter.packages.${pkgs.stdenv.hostPlatform.system}.adapterPython;
        username = config.home.username;
        homeConfiguration = "${config.home.username}@${hostName}";
      })
    ];
  };
}
