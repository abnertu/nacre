# Invariants spanning several options; option types check single values.
{ config, lib, ... }:
let
  users = config.users.users;
  inherit (config) deployment;
  user = users.${deployment.username} or null;
  homes = map (value: value.homeDirectory) (builtins.attrValues users);
  etcNames = builtins.attrNames (lib.filterAttrs (_: entry: entry.enable) config.environment.etc);
  reserved = config.arch.etcReserved;
  isReserved =
    name:
    lib.any (
      path: if lib.hasSuffix "/" path then lib.hasPrefix path name || name + "/" == path else name == path
    ) reserved;
  badName =
    name:
    name == ""
    || lib.hasPrefix "/" name
    || lib.hasSuffix "/" name
    || lib.any (part: part == "" || part == "." || part == "..") (lib.splitString "/" name);
  # Paths that authored units and drop-ins render to, relative to /etc.
  unitPaths = lib.mapAttrsToList (
    name: unit:
    if unit.overrideStrategy == "asDropin" then
      "systemd/system/${name}.d/overrides.conf"
    else
      "systemd/system/${name}"
  ) (lib.filterAttrs (_: unit: unit.enable && unit.text != null) config.systemd.units);
  etcAssertions = lib.concatMap (name: [
    {
      assertion = !builtins.elem name unitPaths;
      message = "environment.etc.\"${name}\" is the file of a systemd.units declaration";
    }
    {
      assertion = !badName name;
      message = "environment.etc.\"${name}\" must be a relative path without empty, . or .. components";
    }
    {
      assertion = badName name || !isReserved name;
      message = "environment.etc.\"${name}\" names a path that another Nacre owner writes";
    }
    {
      assertion = !lib.any (other: lib.hasPrefix "${name}/" other) etcNames;
      message = "environment.etc.\"${name}\" is a directory of another entry";
    }
    {
      assertion = config.environment.etc.${name}.contentError == null;
      message = toString config.environment.etc.${name}.contentError;
    }
  ]) etcNames;
in
{
  assertions = etcAssertions ++ [
    {
      assertion = !config.services.gitlabRunner.enable || config.services.gitlabRunner.configFiles != [ ];
      message = "services.gitlabRunner.enable requires at least one public instance file";
    }
    {
      assertion =
        !config.services.gitlabRunner.enable
        || (config.virtualization.enable && config.virtualization.podman.enable);
      message = "services.gitlabRunner.enable requires virtualization.enable and virtualization.podman.enable";
    }
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
