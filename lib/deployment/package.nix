# The deployment wrapper: Arch convergence first, then the embedded home.
{
  lib,
  pkgs,
  deploymentName,
  arch-switch,
  home-switch,
}:
pkgs.writeShellApplication {
  name = deploymentName;
  text = ''
    readonly deployment_name=${lib.escapeShellArg deploymentName}
    readonly arch_switch=${arch-switch}/bin/arch-switch
    readonly home_switch=${home-switch}/bin/home-switch
  ''
  + builtins.readFile ./deploy.sh;
}
