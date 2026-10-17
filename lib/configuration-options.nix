{ lib }:
let
  inherit (lib) mkOption types;
  enable = description: (lib.mkEnableOption description) // { default = true; };
  option =
    type: default: description:
    mkOption { inherit type default description; };
  section = options: option (types.submodule { inherit options; }) { } "Capability settings.";
  switches =
    names:
    lib.genAttrs names (name: {
      enable = enable name;
    });
  system = import ./system-settings-options.nix { inherit lib; };
  named = types.strMatching "[a-z][a-z0-9_-]*";
  absolute = types.strMatching "/.*";
  # Reuse the owning interface's types rather than admitting arbitrary settings.
  systemSection =
    original: defaults:
    section (
      {
        enable = enable "management of this setting" // {
          default = defaults.enable or true;
        };
      }
      // lib.mapAttrs (
        name: opt:
        mkOption (
          (lib.filterAttrs (
            key: _:
            builtins.elem key [
              "type"
              "default"
              "description"
              "example"
              "apply"
            ]
          ) opt)
          // lib.optionalAttrs (builtins.hasAttr name defaults) { default = defaults.${name}; }
        )
      ) (builtins.removeAttrs (original.type.nestedTypes.elemType.getSubOptions [ ]) [ "_module" ])
    );
  user = types.submodule {
    options = {
      description = mkOption {
        type = types.str;
        description = "Login account description.";
      };
      homeDirectory = mkOption {
        type = types.strMatching "/home/[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*";
        description = "Existing login home: named path segments under /home.";
      };
      stateVersion = mkOption {
        type = types.strMatching "[0-9]{2}\\.[0-9]{2}";
        description = "Home Manager compatibility version; do not bump routinely.";
      };
      admin = option types.bool false "Whether this login account is an administrator.";
      groups = option (types.listOf named) [ ] "Additional native login groups.";
      profiles = switches (builtins.attrNames (import ../profiles));
      modules = switches (builtins.attrNames (import ../modules/home));
      homeModules = option (types.listOf types.path) [ ] "Explicit user Home Manager module paths.";
      development = section {
        neovimPath =
          option (types.nullOr absolute) null
            "Absolute path to a local Neovim config git worktree.";
        hyprlandPath =
          option (types.nullOr absolute) null
            "Absolute path to a local Hyprland config git worktree.";
      };
      home =
        option types.deferredModule { }
          "Home Manager overrides merged after reusable configuration.";
    };
  };
in
{
  networking = {
    hostname = {
      enable = enable "native hostname management";
      name = mkOption {
        type = named;
        description = "Host identity and deployment output prefix.";
      };
    };
    networkmanager.enable = enable "NetworkManager";
    # Needs a prepared NetworkManager AP, so hosts opt in.
    hotspot = systemSection system.hotspot { enable = false; };
    firewall = systemSection system.firewall { };
  };
  boot.kernelModules = mkOption {
    type = types.listOf (types.strMatching "[a-zA-Z0-9_-]+");
    default = [ ];
    apply = lib.unique;
    description = "Kernel modules loaded at boot and, when absent, at runtime.";
  };
  boot.kernel.sysctl = option (types.attrsOf (
    types.nullOr (types.either types.str types.int)
  )) { } "Kernel parameters applied at boot and at runtime; null withdraws a default.";
  nixpkgs.hostPlatform = option (types.enum [ "x86_64-linux" ]) "x86_64-linux" "Nix build platform.";
  deployment = {
    platform = option (types.enum [ "arch" ]) "arch" "Native realization platform.";
    username = mkOption {
      type = named;
      description = "Existing administrator to deploy.";
    };
  };
  hardware = {
    graphics = option (types.enum [
      "amd"
      "generic"
    ]) "generic" "Declared graphics hardware.";
    openrazer.enable = lib.mkEnableOption "OpenRazer";
    bluetooth.enable = enable "Bluetooth";
    initramfs = {
      enable = enable "managed initramfs module addition";
      modules = option (types.listOf (types.strMatching "[a-zA-Z0-9_-]+")) [
      ] "Host's explicit early modules.";
      images = mkOption {
        type = types.nonEmptyListOf (types.strMatching "/boot/[^/]+(/[^/]+)*");
        description = "Expected native /boot initramfs images.";
      };
    };
  };
  i18n = systemSection system.locale {
    generated = [ "en_US.UTF-8" ];
    lang = "en_US.UTF-8";
  };
  time = {
    enable = enable "time-zone management";
    timeZone = option system.timeZone.type.nestedTypes.elemType "UTC" "Native zoneinfo name.";
  };
  console = systemSection system.console { keymap = "us"; };
  services = {
    timesyncd = systemSection system.timeSync { };
    journald = systemSection system.journal { storage = "auto"; };
    logind = systemSection system.power {
      powerKey = "poweroff";
      lidSwitch = "suspend";
    };
    fstrim.enable = enable "the native no-catch-up TRIM timer";
    powerProfilesDaemon.enable = enable "power-profiles-daemon";
    tailscale.enable = enable "Tailscale";
    personalAgent.enable = lib.mkEnableOption "the Personal Agent system service";
  };
  # Off by default; the workstation role enables them.
  programs = lib.genAttrs [ "sunshine" "vesktop" "vicinae" ] (name: {
    enable = lib.mkEnableOption name;
  });
  desktop = {
    enable = lib.mkEnableOption "the graphical home composition";
  }
  // switches [
    "hyprpolkitagent"
    "overview"
    "tailscaleTray"
  ];
  users.users = option (types.attrsOf user) { } "Existing human login accounts.";
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
