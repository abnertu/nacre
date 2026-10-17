# Invariants spanning several options; option types check single values.
{ config, lib, ... }:
let
  users = config.users.users;
  deployment = config.deployment;
  user = users.${deployment.username} or null;
  homes = map (value: value.homeDirectory) (builtins.attrValues users);
in
{
  assertions = [
    {
      assertion = lib.all (name: builtins.match "[a-z][a-z0-9_-]*" name != null) (
        builtins.attrNames users
      );
      message = "login usernames must match [a-z][a-z0-9_-]*";
    }
    {
      assertion = user != null;
      message = "deployment.username must name a declared login user";
    }
    {
      assertion = user == null || user.admin;
      message = "the deployment user must be an administrator";
    }
    {
      assertion = user == null || config.role != "workstation" || user.profiles.workstation.enable;
      message = "the workstation role needs the deployment user's workstation profile";
    }
    {
      assertion = builtins.length homes == builtins.length (lib.unique homes);
      message = "login users must have distinct home directories";
    }
    {
      assertion = lib.all (
        image: !lib.elem ".." (lib.splitString "/" image)
      ) config.hardware.initramfs.images;
      message = "initramfs images must stay under /boot";
    }
  ];
}
