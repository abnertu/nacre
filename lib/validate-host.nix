{ lib, raw }:
let
  fields =
    context: allowed: value:
    assert lib.assertMsg (builtins.isAttrs value) "${context} must be an attribute set";
    assert lib.assertMsg (
      lib.subtractLists allowed (builtins.attrNames value) == [ ]
    ) "${context} has unknown fields";
    value;
  named = value: builtins.isString value && builtins.match "[a-z][a-z0-9_-]*" value != null;
  loginHome =
    value:
    builtins.isString value && builtins.match "/home/[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*" value != null;
  strings = value: builtins.isList value && lib.all builtins.isString value;
  host = fields "host" [
    "name"
    "platform"
    "system"
    "deployment"
    "users"
    "gitlabRunners"
    "personalAgent"
    "hardware"
    "ai"
    "virtualization"
    "systemSettings"
    "powerpanel"
    "sysctl"
  ] raw;
  deployment = fields "deployment" [ "username" "profile" ] host.deployment;
  hardware = fields "hardware" [
    "graphics"
    "openrazer"
    "initramfsModules"
    "initramfsImages"
  ] host.hardware;
  profiles = import ../profiles;
  modules = import ../modules/home;
  users = lib.mapAttrs (
    name: rawUser:
    let
      rawDev = rawUser.development or { };
      dev = fields "user ${name}.development" [
        "neovimPath"
        "hyprlandPath"
      ] rawDev;
      user =
        fields "user ${name}"
          [
            "description"
            "homeDirectory"
            "stateVersion"
            "admin"
            "groups"
            "profiles"
            "modules"
            "homeModules"
            "development"
          ]
          (
            rawUser
            // {
              development = {
                neovimPath = dev.neovimPath or null;
                hyprlandPath = dev.hyprlandPath or null;
              };
            }
          );
    in
    assert lib.assertMsg (named name) "invalid login username";
    assert lib.assertMsg (builtins.isString user.description) "user.description must be a string";
    assert lib.assertMsg (builtins.isBool user.admin) "user.admin must be boolean";
    assert lib.assertMsg (loginHome user.homeDirectory)
      "login home must contain named path segments under /home without traversal";
    assert lib.assertMsg (
      builtins.isString user.stateVersion
      && builtins.match "[0-9]{2}\\.[0-9]{2}" user.stateVersion != null
    ) "invalid Home Manager stateVersion";
    assert lib.assertMsg (strings user.groups && lib.all named user.groups) "invalid login groups";
    assert lib.assertMsg (
      strings user.profiles && lib.all (name: builtins.hasAttr name profiles) user.profiles
    ) "unknown profile";
    assert lib.assertMsg (
      strings user.modules && lib.all (name: builtins.hasAttr name modules) user.modules
    ) "unknown home module";
    assert lib.assertMsg (
      builtins.isList user.homeModules && lib.all builtins.isPath user.homeModules
    ) "homeModules must contain Nix paths";
    assert lib.assertMsg (
      user.development.neovimPath == null
      || (builtins.isString user.development.neovimPath && lib.hasPrefix "/" user.development.neovimPath)
    ) "development.neovimPath must be an absolute path or null";
    assert lib.assertMsg (
      user.development.hyprlandPath == null
      || (
        builtins.isString user.development.hyprlandPath && lib.hasPrefix "/" user.development.hyprlandPath
      )
    ) "development.hyprlandPath must be an absolute path or null";
    user
  ) host.users;
in
assert lib.assertMsg (named host.name) "invalid host name";
assert lib.assertMsg (
  host.platform == "arch" && host.system == "x86_64-linux"
) "only x86_64 Arch hosts are supported";
assert lib.assertMsg (
  named deployment.username && builtins.hasAttr deployment.username users
) "unknown deployment user";
assert lib.assertMsg users.${deployment.username}.admin "deployment user must be an administrator";
assert lib.assertMsg (builtins.elem deployment.profile
  users.${deployment.username}.profiles
) "deployment profile must be selected by its user";
assert lib.assertMsg (builtins.elem hardware.graphics [
  "amd"
  "generic"
]) "unsupported graphics selection";
assert lib.assertMsg (builtins.isBool hardware.openrazer) "hardware.openrazer must be boolean";
assert lib.assertMsg (
  strings hardware.initramfsModules
  && lib.all (value: builtins.match "[a-zA-Z0-9_-]+" value != null) hardware.initramfsModules
) "invalid initramfs modules";
assert lib.assertMsg (
  strings hardware.initramfsImages
  && hardware.initramfsImages != [ ]
  && lib.all (
    value: lib.hasPrefix "/boot/" value && !lib.hasInfix ".." value
  ) hardware.initramfsImages
) "initramfs images must be under /boot";
assert lib.assertMsg (
  let
    homes = map (user: user.homeDirectory) (builtins.attrValues users);
  in
  builtins.length homes == builtins.length (lib.unique homes)
) "login users must have distinct home directories";
builtins.deepSeq users (
  host
  // {
    inherit users hardware deployment;
    ai = import ../modules/ai/interface.nix {
      inherit lib;
      raw = host.ai or { };
    };
    virtualization = import ../modules/virtualization/interface.nix {
      inherit lib;
      raw = host.virtualization or { };
    };
    systemSettings = import ./system-settings.nix {
      inherit lib;
      raw = host.systemSettings or { };
    };
    gitlabRunners = host.gitlabRunners or { };
    personalAgent = host.personalAgent or false;
    powerpanel = import ../modules/powerpanel/interface.nix {
      inherit lib;
      raw = host.powerpanel or { };
    };
  }
)
