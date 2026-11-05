# Shared options of every Nacre machine: host identity, native settings,
# packages, hardware, desktop switches and login accounts. Feature options
# live in each feature's module.nix; cross-field rules live in
# configuration-assertions.nix.
{ lib }:
let
  inherit (lib) mkOption types;

  system = import ./system-settings-options.nix { inherit lib; };
  profileRegistry = import ../profiles;
  homeModuleRegistry = import ../modules/home;

  named = types.strMatching "[a-z][a-z0-9_-]*";
  absolute = types.strMatching "/.*";
  packageName = types.strMatching "[a-z0-9@._+-]+";
  moduleName = types.strMatching "[a-zA-Z0-9_-]+";

  # An enable option that defaults to true.
  enabledByDefault =
    description:
    lib.mkEnableOption description
    // {
      default = true;
    };

  # One enable option for each registry entry, described by the registry.
  switches =
    registry:
    lib.mapAttrs (_: entry: {
      enable = enabledByDefault entry.description;
    }) registry;

  # A native setting exposed as user options. The field types, defaults and
  # descriptions come from system-settings-options.nix, the one owner of these
  # types; `defaults` overrides field defaults and `enable` withdraws management.
  systemSection =
    {
      setting,
      description,
      defaults ? { },
    }:
    let
      fields = builtins.removeAttrs (setting.type.nestedTypes.elemType.getSubOptions [ ]) [
        "_module"
      ];
      copied = [
        "type"
        "default"
        "defaultText"
        "description"
        "example"
        "apply"
      ];
      field =
        name: original:
        mkOption (
          lib.filterAttrs (key: _: builtins.elem key copied) original
          // lib.optionalAttrs (defaults ? ${name}) { default = defaults.${name}; }
        );
    in
    mkOption {
      type = types.submodule {
        options = {
          enable = lib.mkEnableOption "management of the ${description}" // {
            default = defaults.enable or true;
          };
        }
        // lib.mapAttrs field (builtins.removeAttrs fields [ "enable" ]);
      };
      default = { };
      description = "Management of the ${description}.";
    };

  user = types.submodule {
    options = {
      description = mkOption {
        type = types.str;
        description = "Login account description (the GECOS field).";
      };
      homeDirectory = mkOption {
        type = types.strMatching "/home/[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*";
        description = "Existing login home: named path segments under /home.";
      };
      stateVersion = mkOption {
        type = types.strMatching "[0-9]{2}\\.[0-9]{2}";
        description = "Home Manager compatibility version; keep it fixed through routine updates.";
      };
      admin = mkOption {
        type = types.bool;
        default = false;
        description = "Whether this login account is an administrator.";
      };
      groups = mkOption {
        type = types.listOf named;
        default = [ ];
        description = "Additional native groups of the login account.";
      };
      profiles = switches profileRegistry;
      modules = switches homeModuleRegistry;
      homeModules = mkOption {
        type = types.listOf types.path;
        default = [ ];
        description = "Additional Home Manager modules for this account.";
      };
      sources = mkOption {
        type = types.submodule {
          options = {
            neovim = mkOption {
              type = types.nullOr types.path;
              default = null;
              # Normalize sources to strings instead of traversing flake inputs.
              apply = source: if source == null then null else "${source}";
              description = "Neovim configuration source projected into ~/.config; null uses Nacre's pinned input.";
            };
            hyprland = mkOption {
              type = types.nullOr types.path;
              default = null;
              apply = source: if source == null then null else "${source}";
              description = "Hyprland configuration source projected into ~/.config; null uses Nacre's pinned input.";
            };
          };
        };
        default = { };
        description = "Configuration sources that replace Nacre's pinned inputs for this account.";
      };
      development = mkOption {
        type = types.submodule {
          options = {
            neovimPath = mkOption {
              type = types.nullOr absolute;
              default = null;
              description = "Absolute path to a local Neovim configuration worktree, linked instead of a source.";
            };
            hyprlandPath = mkOption {
              type = types.nullOr absolute;
              default = null;
              description = "Absolute path to a local Hyprland configuration worktree, linked instead of a source.";
            };
          };
        };
        default = { };
        description = "Local worktrees that the account develops in place.";
      };
      home = mkOption {
        type = types.deferredModule;
        default = { };
        description = "Home Manager overrides merged after the reusable configuration.";
      };
    };
  };
in
{
  networking = {
    hostname = {
      enable = enabledByDefault "native hostname management";
      name = mkOption {
        type = named;
        description = "Host identity and deployment output prefix.";
      };
    };
    networkmanager.enable = enabledByDefault "NetworkManager";
    # Needs a prepared NetworkManager AP, so hosts opt in.
    hotspot = systemSection {
      setting = system.hotspot;
      description = "NetworkManager access point";
      defaults.enable = false;
    };
    firewall = systemSection {
      setting = system.firewall;
      description = "UFW firewall";
    };
  };

  boot = {
    kernelModules = mkOption {
      type = types.listOf moduleName;
      default = [ ];
      apply = lib.unique;
      description = "Kernel modules loaded at boot and, when absent, at runtime.";
    };
    kernel.sysctl = mkOption {
      type = types.attrsOf (types.nullOr (types.either types.str types.int));
      default = { };
      example = {
        "vm.swappiness" = 10;
      };
      description = "Kernel parameters applied at boot and at runtime; null withdraws a default.";
    };
  };

  packages = {
    hold = mkOption {
      type = types.listOf packageName;
      default = [ ];
      apply = lib.unique;
      example = [ "ghostty" ];
      description = "Installed packages that update leaves at their current version, as with pacman's --ignore; missing ones still install.";
    };
    extra = {
      pacman = mkOption {
        type = types.listOf packageName;
        default = [ ];
        example = [ "obsidian" ];
        description = "Additional Arch repository packages for this machine.";
      };
      aur = mkOption {
        type = types.listOf packageName;
        default = [ ];
        example = [ "onlyoffice-bin" ];
        description = "Additional AUR packages for this machine, installed through yay as the login user.";
      };
    };
  };

  nix.settings = mkOption {
    type = types.attrsOf (
      types.oneOf [
        types.bool
        types.int
        types.str
        (types.listOf types.str)
      ]
    );
    default = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      max-jobs = "auto";
      cores = 0;
      max-substitution-jobs = 64;
      http-connections = 50;
    };
    description = "Settings for the managed block in /etc/nix/nix.conf; trusted-users is added for the deployment user.";
  };

  nixpkgs.hostPlatform = mkOption {
    type = types.enum [ "x86_64-linux" ];
    default = "x86_64-linux";
    description = "Nix build platform.";
  };

  deployment = {
    platform = mkOption {
      type = types.enum [ "arch" ];
      default = "arch";
      description = "Native realization platform.";
    };
    username = mkOption {
      type = named;
      description = "Existing administrator to deploy.";
    };
  };

  hardware = {
    graphics = mkOption {
      type = types.enum [
        "amd"
        "generic"
      ];
      default = "generic";
      description = "Declared graphics hardware; amd enables the ROCm and Vulkan paths.";
    };
    openrazer.enable = lib.mkEnableOption "OpenRazer";
    bluetooth.enable = enabledByDefault "Bluetooth";
    initramfs = {
      enable = enabledByDefault "managed initramfs module addition";
      modules = mkOption {
        type = types.listOf moduleName;
        default = [ ];
        description = "Modules that the host must load early, added to the initramfs.";
      };
      images = mkOption {
        type = types.nonEmptyListOf (types.strMatching "/boot/[^/]+(/[^/]+)*");
        description = "Expected native /boot initramfs images.";
      };
    };
  };

  i18n = systemSection {
    setting = system.locale;
    description = "locales and the system language";
    defaults = {
      generated = [ "en_US.UTF-8" ];
      lang = "en_US.UTF-8";
    };
  };

  time = {
    enable = enabledByDefault "time zone management";
    timeZone = mkOption {
      type = system.timeZone.type.nestedTypes.elemType;
      default = "UTC";
      description = "Native zoneinfo name.";
    };
  };

  console = systemSection {
    setting = system.console;
    description = "virtual console keymap and font";
    defaults.keymap = "us";
  };

  services = {
    timesyncd = systemSection {
      setting = system.timeSync;
      description = "systemd-timesyncd time synchronization";
    };
    journald = systemSection {
      setting = system.journal;
      description = "systemd-journald storage and retention";
      defaults.storage = "auto";
    };
    logind = systemSection {
      setting = system.power;
      description = "systemd-logind power key and lid actions";
      defaults = {
        powerKey = "poweroff";
        lidSwitch = "suspend";
      };
    };
    fstrim.enable = enabledByDefault "the native no-catch-up TRIM timer";
    powerProfilesDaemon.enable = enabledByDefault "power-profiles-daemon";
    tailscale.enable = enabledByDefault "Tailscale";
  };

  # Off by default; the workstation role enables them.
  programs = {
    sunshine.enable = lib.mkEnableOption "the Sunshine game-streaming host";
    vesktop.enable = lib.mkEnableOption "the Vesktop Discord client";
    vicinae.enable = lib.mkEnableOption "the Vicinae launcher";
  };

  desktop = {
    enable = lib.mkEnableOption "the graphical home composition";
    hyprpolkitagent.enable = enabledByDefault "the Hyprland Polkit authentication agent";
    overview.enable = enabledByDefault "the Quickshell workspace overview";
    tailscaleTray.enable = enabledByDefault "the Tailscale tray icon";
  };

  users.users = mkOption {
    type = types.attrsOf user;
    default = { };
    description = "Existing human login accounts, keyed by user name.";
  };

  assertions = mkOption {
    type = types.listOf (
      types.submodule {
        options = {
          assertion = mkOption { type = types.bool; };
          message = mkOption { type = types.str; };
        };
      }
    );
    default = [ ];
    internal = true;
    description = "Cross-field invariants checked after evaluation.";
  };
}
