# Compose one complete deployment from configuration modules. The flake builds
# the operator's configuration with this; tests add overriding modules.
{
  inputs,
  modules ? [ ../configuration.nix ],
}:
let
  inherit (inputs) nixpkgs;
  inherit (nixpkgs) lib;
  mkHomeConfiguration = import ./mk-home-configuration.nix { inherit inputs; };
  configuration = import ./eval-configuration.nix { inherit lib modules; };
  host = configuration.host;
  capabilities = configuration.capabilities;
  system = host.system;
  pkgs = nixpkgs.legacyPackages.${system};
  homes = lib.mapAttrs' (
    username: user:
    lib.nameValuePair "${username}@${host.name}" (mkHomeConfiguration {
      inherit username user capabilities;
      inherit (host)
        ai
        platform
        hardware
        system
        ;
      hostName = host.name;
    })
  ) host.users;
  deployment = host.deployment;
  deploymentUser =
    host.users.${deployment.username} or (throw "unknown deployment user: ${deployment.username}");
  deploymentName = "${host.name}-${deployment.profile}";
  homeConfigurationName = "${deployment.username}@${host.name}";
  nixAdapter = inputs.nix-adapter.packages.${system}.nix-adapter;
  adapterPython = inputs.nix-adapter.packages.${system}.adapterPython;
  runners = import ../modules/gitlab-runner {
    inherit lib pkgs adapterPython;
    gitlab-runner = inputs.gitlab-runner;
    rawInstances = host.gitlabRunners;
  };
  ai = import ../modules/ai {
    inherit lib;
    config = host.ai;
    skillSources = {
      matt-pocock = inputs.matt-pocock-skills;
      vercel = inputs.vercel-skills;
    };
  };
  archAi = import ../platforms/arch/ai {
    inherit lib pkgs;
    config = host.ai;
    artifacts = ai.artifacts;
    hardware = host.hardware;
    tailscale = capabilities.tailscale;
  };
  virtualization = import ../modules/virtualization {
    inherit lib;
    config = host.virtualization;
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
  nativePackages = import ../platforms/arch/packages.nix {
    inherit lib capabilities;
    hardware = host.hardware;
    modulePackages = runners.requiredPackages ++ virtualization.requiredPackages;
    systemSettings = host.systemSettings;
    moduleAurPackages = ai.aurPackages ++ powerpanel.aurPackages;
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
    moduleGroups = virtualization.loginGroups ++ powerpanel.loginGroups;
    moduleSystemUnits = virtualization.systemUnits ++ powerpanel.systemUnits;
    username = deployment.username;
    packages = nativePackages;
    hardware = host.hardware;
    sysctl = host.sysctl;
    aiConfig = host.ai;
    aiArtifacts = ai.artifacts;
    personalAgentPackage = inputs.personal-agent.packages.${system}.personal-agent;
    personalAgentConfig = host.personalAgent;
  };
  llama-prepare = import ../modules/ai/package.nix {
    inherit lib pkgs adapterPython;
    artifacts = ai.artifacts;
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
    runners
    archAi
    arch-switch
    llama-prepare
    home-switch
    ;
  noctaliaEnabled = builtins.elem "noctalia-config" deploymentUser.modules;
  noctalia-config = import ../modules/home/noctalia-config/package.nix {
    inherit pkgs adapterPython;
    username = deployment.username;
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
