# The operator command. It knows the deployment's name but not its contents,
# so the home generation that installs it does not depend on the deployment.
{
  lib,
  pkgs,
  deploymentName,
}:
pkgs.writeShellApplication {
  name = "nacre";
  runtimeInputs = with pkgs; [
    coreutils
    gawk
    git
    gnugrep
  ];
  text = ''
    readonly deployment=${lib.escapeShellArg deploymentName}
    readonly nacre_version=${lib.escapeShellArg (lib.trim (builtins.readFile ../../../VERSION))}
  ''
  + builtins.readFile ../nix.sh
  + builtins.readFile ./nacre.sh;
}
