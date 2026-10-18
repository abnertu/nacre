# Flake outputs for one machine. Nacre's own flake applies this to its
# configuration; a machine's flake calls
#   nacre.lib.mkFlake { modules = [ ./configuration.nix ]; }
# Every machine exposes the same attribute names, so one nacre command works
# with any of them.
{ inputs }:
{ modules }:
let
  d = import ./mk-deployment.nix { inherit inputs modules; };
  inherit (d) lib system;
  app = package: description: {
    type = "app";
    program = lib.getExe package;
    meta = { inherit description; };
  };
in
{
  homeConfigurations = d.homes;
  # A queryable normalized configuration, not a NixOS system.
  lib = {
    configuration = d.configuration.config;
    configurations.${d.host.name} = d.configuration.config;
    inherit (d) deploymentName;
    runnerctlEnabled = d.runners.packages != { };
  };

  packages.${system} = {
    inherit (d)
      arch-switch
      home-switch
      llama-prepare
      nacre
      deployment
      ;
    ${d.deploymentName} = d.deployment;
    default = d.nacre;
  }
  // lib.optionalAttrs d.noctaliaEnabled { inherit (d) noctalia-config; }
  // d.runners.packages;

  apps.${system} = {
    nacre = app d.nacre "Install, plan, switch and inspect this machine";
    deployment = app d.deployment "Build and activate ${d.deploymentName}";
    ${d.deploymentName} = app d.deployment "Build and activate ${d.deploymentName}";
    arch-switch = app d.arch-switch "Converge Arch-native policy";
    home-switch = app d.home-switch "Activate ${d.homeConfigurationName} through Home Manager";
    llama-prepare = app d.llama-prepare "Prepare the pinned llama.cpp build and models";
  }
  // lib.optionalAttrs d.noctaliaEnabled {
    noctalia-config = app d.noctalia-config "Capture or deploy reviewed Noctalia preferences";
  }
  // d.runners.apps;
}
