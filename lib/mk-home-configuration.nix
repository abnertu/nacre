# The Home Manager configuration of one login account: profiles, home
# modules, AI home files and the account's own modules.
{ inputs }:
{
  system,
  hostName,
  platform,
  hardware,
  capabilities,
  username,
  user,
  ai ? {
    enable = false;
  },
  # Packages every home on this host receives, such as the operator command.
  packages ? [ ],
}:
let
  pkgs = import inputs.nixpkgs {
    inherit system;
    config.allowUnfree = true;
  };
  profileRegistry = import ../profiles;
  moduleRegistry = import ../modules/home;
  resolve =
    registry: kind: name:
    if builtins.hasAttr name registry then
      registry.${name}.module
    else
      throw "unknown ${kind}: ${name}";
  userNormalized = user // {
    sources = {
      neovim = user.sources.neovim or null;
      hyprland = user.sources.hyprland or null;
    };
    development = {
      neovimPath = user.development.neovimPath or null;
      hyprlandPath = user.development.hyprlandPath or null;
    };
  };
in
assert inputs.nixpkgs.lib.assertMsg (platform == "arch") "unsupported platform: ${platform}";
inputs.home-manager.lib.homeManagerConfiguration {
  inherit pkgs;

  extraSpecialArgs = {
    inherit
      inputs
      hostName
      platform
      hardware
      capabilities
      ;
    user = userNormalized;
  };

  modules = [
    {
      home = {
        inherit username;
        inherit (userNormalized) homeDirectory;
        inherit (userNormalized) stateVersion;
      };

      programs.home-manager.enable = true;
      home.packages = packages;
    }
  ]
  ++ [
    (import ../modules/ai {
      lib = inputs.nixpkgs.lib;
      config = ai;
      ghSource = pkgs.gh.src;
    }).homeModule
  ]
  ++ [ (userNormalized.homeConfig or { }) ]
  ++ [
    ({ lib, ... }: {
      options.workstation.capabilities = lib.mkOption {
        type = lib.types.attrsOf (
          lib.types.submodule {
            options.enable = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Whether the account enables this home capability.";
            };
          }
        );
        default = { };
        internal = true;
        description = "Home capabilities that the deployment enables, keyed by home module name.";
      };
      config.workstation.capabilities = lib.genAttrs [ "noctalia-config" ] (name: {
        enable = builtins.elem name userNormalized.modules;
      });
    })
  ]
  ++ [
    ../modules/home/noctalia-config
    ../modules/home/fcitx5.nix
  ]
  ++ userNormalized.homeModules
  ++ map (resolve profileRegistry "profile") (
    builtins.filter (name: capabilities.desktop.enable || name != "workstation") userNormalized.profiles
  )
  ++ map (resolve moduleRegistry "home module") userNormalized.modules;
}
