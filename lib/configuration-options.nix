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
  # Reuse the owning interface's types rather than admitting arbitrary settings.
  systemSection =
    original: defaults:
    section (
      {
        enable = enable "management of this setting";
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
        type = types.str;
        description = "Existing login home under /home.";
      };
      stateVersion = mkOption {
        type = types.str;
        description = "Home Manager compatibility version; do not bump routinely.";
      };
      admin = option types.bool false "Whether this login account is an administrator.";
      groups = option (types.listOf types.str) [ ] "Additional native login groups.";
      profiles = switches (builtins.attrNames (import ../profiles));
      modules = switches (builtins.attrNames (import ../modules/home));
      homeModules = option (types.listOf types.path) [ ] "Explicit user Home Manager module paths.";
      development = section {
        neovimPath =
          option (types.nullOr types.str) null
            "Absolute path to a local Neovim config git worktree.";
        hyprlandPath =
          option (types.nullOr types.str) null
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
        type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9.-]*";
        description = "Host identity and deployment output prefix.";
      };
    };
    networkmanager.enable = enable "NetworkManager";
    hotspot = systemSection system.hotspot { };
    firewall = systemSection system.firewall { };
  };
  boot.kernel.sysctl = option (types.attrsOf (
    types.nullOr (types.either types.str types.int)
  )) { } "Kernel parameters applied at boot and at runtime; null withdraws a default.";
  nixpkgs.hostPlatform = option (types.enum [ "x86_64-linux" ]) "x86_64-linux" "Nix build platform.";
  deployment = {
    platform = option (types.enum [ "arch" ]) "arch" "Native realization platform.";
    username = mkOption {
      type = types.str;
      description = "Existing administrator to deploy.";
    };
    profile = option (types.enum (
      builtins.attrNames (import ../profiles)
    )) "workstation" "Label for the complete user composition.";
  };
  hardware = {
    graphics = option (types.enum [
      "amd"
      "generic"
    ]) "generic" "Declared graphics hardware.";
    openrazer.enable = enable "OpenRazer";
    bluetooth.enable = enable "Bluetooth";
    initramfs = {
      enable = enable "managed initramfs module addition";
      modules = option (types.listOf types.str) [ ] "Host's explicit early modules.";
      images = mkOption {
        type = types.nonEmptyListOf types.str;
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
    gitlabRunner = import ../modules/gitlab-runner/options.nix { inherit lib; };
    personalAgent = {
      enable = (lib.mkEnableOption "the Personal Agent system service") // {
        default = true;
      };
    };
    powerpanel = import ../modules/powerpanel/options.nix { inherit lib; };
  };
  programs = {
    ai = import ../modules/ai/options.nix { inherit lib; };
  }
  // switches [
    "sunshine"
    "vesktop"
    "vicinae"
  ];
  desktop = {
    enable = enable "the graphical home composition";
  }
  // switches [
    "hyprpolkitagent"
    "overview"
    "tailscaleTray"
  ];
  virtualization = import ../modules/virtualization/options.nix { inherit lib; };
  users.users = option (types.attrsOf user) { } "Existing human login accounts.";
}
