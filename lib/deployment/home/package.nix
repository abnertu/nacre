# The home-switch entry point that activates the embedded home.
{ pkgs, activationPackage }:
pkgs.writeShellApplication {
  name = "home-switch";
  text = ''
    readonly activation_package=${activationPackage}
  ''
  + builtins.readFile ./switch.sh;
}
