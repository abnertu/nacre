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
    if builtins.hasAttr name registry then registry.${name} else throw "unknown ${kind}: ${name}";
  userNormalized = user // {
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
        homeDirectory = userNormalized.homeDirectory;
        stateVersion = userNormalized.stateVersion;
      };

      programs.home-manager.enable = true;
      home.packages = packages;
    }
  ]
  ++ [
    (import ../modules/ai {
      lib = inputs.nixpkgs.lib;
      config = ai;
      skillSources = {
        matt-pocock = inputs.matt-pocock-skills;
        vercel = inputs.vercel-skills;
      };
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
            };
          }
        );
        default = { };
        internal = true;
      };
      config.workstation.capabilities = lib.genAttrs [ "noctalia-config" ] (name: {
        enable = builtins.elem name userNormalized.modules;
      });
    })
  ]
  ++ [
    ../modules/home/noctalia-config
  ]
  ++ userNormalized.homeModules
  ++ map (resolve profileRegistry "profile") (
    builtins.filter (name: capabilities.desktop.enable || name != "workstation") userNormalized.profiles
  )
  ++ map (resolve moduleRegistry "home module") userNormalized.modules;
}
