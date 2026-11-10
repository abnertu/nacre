# Compose one complete deployment from configuration modules. Machine flakes
# reach it through mkFlake; checks pass the fixture plus overriding modules.
{
  inputs,
  modules,
}:
let
  inherit (inputs) nixpkgs;
  inherit (nixpkgs) lib;
  mkHomeConfiguration = import ./mk-home-configuration.nix { inherit inputs; };
  configuration = import ./eval-configuration.nix {
    inherit lib;
    modules = modules ++ [ { _module.args.runnerctl = runnerctl; } ];
  };
  inherit (configuration) host;
  inherit (configuration) capabilities;
  # The configured extension refers back to pkgs. Do not derive its package
  # set through host, which forces every extension manifest for validation.
  system = configuration.config.nixpkgs.hostPlatform;
  pkgs = nixpkgs.legacyPackages.${system};
  runnerPolicy = configuration.config.services.gitlabRunner;
  runnerPublic = import ../modules/gitlab-runner/interface.nix {
    inherit lib;
    inherit (runnerPolicy) configFiles;
  };
  runnerctl = import ../modules/gitlab-runner/configured-controller.nix {
    inherit lib pkgs;
    inherit (runnerPublic) root configFiles;
    controller =
      (inputs.gitlab-runner
        or (throw "Runner controller input is unavailable; complete compatible controller input adoption")
      ).packages.${system}.runnerctl;
  };
  homes = lib.mapAttrs' (
    username: user:
    lib.nameValuePair "${username}@${host.name}" (mkHomeConfiguration {
      inherit username user capabilities;
      packages = [ nacre ];
      inherit (host)
        ai
        platform
        hardware
        system
        ;
      hostName = host.name;
    })
  ) host.users;
  inherit (host) deployment;
  deploymentUser =
    host.users.${deployment.username} or (throw "unknown deployment user: ${deployment.username}");
  deploymentName = "${host.name}-${host.role}";
  homeConfigurationName = "${deployment.username}@${host.name}";
  nacre = import ./cli/nacre { inherit lib pkgs; };
  nixAdapter = inputs.nix-adapter.packages.${system}.nix-adapter;
  adapterPython = inputs.nix-adapter.packages.${system}.adapterPython;
  ai = import ../modules/ai {
    inherit lib;
    config = host.ai;
    skillSources = {
      inherit (inputs)
        matt-pocock-skills
        obsidian-skills
        vercel-skills
        abnertu-skills
        ;
      gh = pkgs.gh.src;
    };
  };
  archAi = import ../platforms/arch/ai {
    inherit lib pkgs;
    config = host.ai;
    inherit (ai) artifacts;
    inherit (capabilities) tailscale;
  };
  powerpanel = import ../modules/powerpanel {
    inherit lib pkgs;
    config = host.powerpanel;
  };
  systemSettings = import ../platforms/arch/system {
    inherit lib pkgs;
    config = host.systemSettings;
    hostName = host.name;
  };
  arch-switch = import ../platforms/arch/package.nix {
    inherit
      lib
      pkgs
      deploymentUser
      capabilities
      systemSettings
      powerpanel
      adapterPython
      ;
    inherit (deployment) username;
    inherit (host) arch;
    inherit (host) hardware;
    inherit (host) sysctl kernelModules nixSettings;
    aiConfig = host.ai;
    aiArtifacts = ai.artifacts;
  };
  llama-prepare = import ../modules/ai/package.nix {
    inherit lib pkgs adapterPython;
    inherit (ai) artifacts;
  };
  home-switch = import ./deployment/home/package.nix {
    inherit pkgs;
    activationPackage = homes.${homeConfigurationName}.activationPackage;
  };
in
{
  inherit
    lib
    pkgs
    system
    configuration
    host
    homes
    deploymentUser
    deploymentName
    homeConfigurationName
    nixAdapter
    adapterPython
    archAi
    arch-switch
    llama-prepare
    home-switch
    nacre
    runnerctl
    ;
  noctaliaEnabled = builtins.elem "noctalia-config" deploymentUser.modules;
  runnerDeclared = runnerPolicy.configFiles != [ ];
  noctalia-config = import ../modules/home/noctalia-config/package.nix {
    inherit pkgs adapterPython;
    inherit (deployment) username;
    homeConfiguration = homeConfigurationName;
  };
  deployment = import ./deployment/package.nix {
    inherit
      lib
      pkgs
      deploymentName
      arch-switch
      home-switch
      ;
  };
}
