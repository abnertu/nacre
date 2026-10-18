# fcitx5 settings as policy. fcitx5 rewrites its files whenever it saves, so
# the whole configuration directory is one read-only store link, as with Home
# Manager's own fcitx5 module: fcitx5-configtool cannot save, and changes go
# through these options. User data such as learned phrases stays writable
# under ~/.local/share/fcitx5. The packages come from Arch.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption types;
  cfg = config.workstation.fcitx5;
  ini = lib.generators.toINI { };
  layout = lib.removePrefix "keyboard-" (builtins.head cfg.inputMethods);
  profile = {
    GroupOrder."0" = "Default";
    "Groups/0" = {
      Name = "Default";
      "Default Layout" = layout;
      # Toggling the input method on activates the second entry.
      DefaultIM = lib.last (lib.take 2 cfg.inputMethods);
    };
  }
  // lib.listToAttrs (
    lib.imap0 (index: name: {
      name = "Groups/0/Items/${toString index}";
      value.Name = name;
    }) cfg.inputMethods
  );
in
{
  options.workstation.fcitx5 = {
    inputMethods = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [
        "keyboard-us"
        "chewing"
      ];
      description = "Input methods of the default group, starting with the keyboard layout used while the input method is off. Empty leaves fcitx5's configuration unmanaged.";
    };
    globalOptions = mkOption {
      type = types.attrsOf (types.attrsOf types.str);
      default = { };
      example = {
        Behavior.PreeditEnabledByDefault = "False";
      };
      description = "Sections of fcitx5's global config that differ from its defaults, as fcitx5 itself writes them.";
    };
  };

  config = lib.mkIf (cfg.inputMethods != [ ]) {
    assertions = [
      {
        assertion = lib.hasPrefix "keyboard-" (builtins.head cfg.inputMethods);
        message = "workstation.fcitx5.inputMethods must start with a keyboard layout such as keyboard-us.";
      }
    ];
    xdg.configFile.fcitx5.source = pkgs.linkFarm "fcitx5-config" [
      {
        name = "config";
        path = pkgs.writeText "fcitx5-config" (ini cfg.globalOptions);
      }
      {
        name = "profile";
        path = pkgs.writeText "fcitx5-profile" (ini profile);
      }
    ];
  };
}
