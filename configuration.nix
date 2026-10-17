# Single entry point: imported values are defaults; ordinary definitions here win.
# The examples below use these module arguments.
# deadnix: skip
{ config, lib, ... }:
# let
#   archUsers = import ./hosts/arch/users.nix { inherit config lib; };
# in
{
  imports = [ ./hosts/arch ];

  # Example capability overrides:
  # networking.hotspot.enable = false;
  # networking.firewall.enable = false;

  # Example deployment user override (avoids module recursion):
  # deployment.username = "abner";
  # users.users = lib.mkForce {
  #   abner = archUsers.abnertu // {
  #     description = "Abner";
  #     homeDirectory = "/home/abner";
  #   };
  # };

  users.users.abnertu.development = {
    neovimPath = "/home/abnertu/codebase/orbitvim";
    hyprlandPath = "/home/abnertu/codebase/hypr";
  };

  # Example home configuration override:
  # users.users.abnertu.home.programs.git.settings.init.defaultBranch = "main";
}
