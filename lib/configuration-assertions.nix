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
  unitPath =
    name: unit:
    if unit.overrideStrategy == "asDropin" then
      "systemd/system/${name}.d/overrides.conf"
    else
      "systemd/system/${name}";
  authoredUnits = lib.filterAttrs (_: unit: unit.enable && unit.text != null) config.systemd.units;
  unitAssertions = lib.mapAttrsToList (name: unit: {
    assertion = !isReserved (unitPath name unit);
    message = "systemd.units.\"${name}\" renders a path that another Nacre owner writes";
  }) authoredUnits;
  unitPaths = lib.mapAttrsToList (
    name: unit:
    if unit.overrideStrategy == "asDropin" then
      "systemd/system/${name}.d/overrides.conf"
    else
      "systemd/system/${name}"
  ) (lib.filterAttrs (_: unit: unit.enable && unit.text != null) config.systemd.units);
  inherit (builtins) storeDir;
  underTextPath =
    name: lib.any (path: name == path || lib.hasPrefix "${path}/" name) config.arch.textPaths;
  # A source is a Nix path to a regular file, or a string with store context;
  # a target is an absolute native path. Neither may hide text that adapters read.
  kindAssertions =
    name: entry:
    let
      inherit (entry) source target;
      label = "environment.etc.\"${name}\"";
    in
    lib.optionals (entry.kind == "source") [
      {
        assertion =
          if builtins.isPath source then
            builtins.readFileType source == "regular"
          else
            builtins.hasContext source && lib.hasPrefix "${storeDir}/" source;
        message = "${label}.source must be a Nix path to a regular file or a store path with its context";
      }
    ]
    ++ lib.optionals (entry.kind == "target") [
      {
        assertion = lib.hasPrefix "/" target && !lib.hasPrefix "${storeDir}/" target && target != storeDir;
        message = "${label}.target must be an absolute path outside ${storeDir}";
      }
      {
        assertion = entry.mode == "0644" && entry.group == "root";
        message = "${label} is a symlink; it keeps the default mode and group";
      }
    ]
    ++
      lib.optionals
        (builtins.elem entry.kind [
          "source"
          "target"
        ])
        [
          {
            assertion = !underTextPath name;
            message = "${label} is at or under a path that an adapter reads as text; declare it with text";
          }
        ];
  etcAssertions = lib.concatMap (
    name:
    [
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
    ]
    ++ kindAssertions name config.environment.etc.${name}
  ) etcNames;
  systemUsers = config.users.systemUsers;
  # A sysusers.d name: lower case, at most 31 characters.
  accountName = name: builtins.match "[a-z_][a-z0-9_-]{0,30}" name != null;
  accountAssertions =
    map (name: {
      assertion = accountName name;
      message = "users.groups.\"${name}\" must match [a-z_][a-z0-9_-]{0,30}";
    }) (builtins.attrNames config.users.groups)
    ++ lib.concatLists (
      lib.mapAttrsToList (name: account: [
        {
          assertion = accountName name;
          message = "users.systemUsers.\"${name}\" must match [a-z_][a-z0-9_-]{0,30}";
        }
        {
          assertion = !users ? ${name};
          message = "users.systemUsers.\"${name}\" is also a login account in users.users";
        }
        {
          assertion = config.users.groups ? ${account.group};
          message = "users.systemUsers.\"${name}\".group ${account.group} is not declared in users.groups";
        }
      ]) systemUsers
    );
  inventories = builtins.attrValues config.arch.inventory;
  requiredBy =
    name:
    lib.attrNames (
      lib.filterAttrs (
        _: inventory:
        inventory.enable && builtins.elem name (inventory.pacman.required ++ inventory.aur.required)
      ) config.arch.inventory
    );
  offered = lib.concatMap (
    inventory: inventory.pacman.defaults ++ inventory.aur.defaults
  ) inventories;
  extra = config.packages.extra.pacman ++ config.packages.extra.aur;
  excludeAssertions = lib.concatMap (name: [
    {
      assertion = requiredBy name == [ ];
      message = "packages.exclude names ${name}, which ${lib.concatStringsSep ", " (requiredBy name)} requires";
    }
    {
      assertion = requiredBy name != [ ] || builtins.elem name offered;
      message = "packages.exclude names ${name}, which no Nacre inventory offers as a default";
    }
    {
      assertion = !builtins.elem name extra;
      message = "packages.exclude and packages.extra both name ${name}";
    }
  ]) config.packages.exclude;
in
{
  assertions =
    etcAssertions
    ++ unitAssertions
    ++ excludeAssertions
    ++ [
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
    ]
    ++ accountAssertions;
}
