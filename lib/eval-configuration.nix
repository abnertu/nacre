{
  lib,
  modules ? [ ../configuration.nix ],
}:
let
  evaluated = lib.evalModules {
    class = "nixConfig";
    modules = [
      { options = import ./configuration-options.nix { inherit lib; }; }
      ./configuration-assertions.nix
      ../platforms/arch/module.nix
      {
        # Container networking and throughput defaults; override individual keys.
        boot.kernel.sysctl = lib.mapAttrs (_: lib.mkDefault) {
          "net.core.default_qdisc" = "fq";
          "net.ipv4.tcp_congestion_control" = "bbr";
          "net.ipv4.ip_forward" = 1;
          "net.ipv6.conf.all.forwarding" = 1;
          "net.bridge.bridge-nf-call-iptables" = 1;
        };
      }
    ]
    ++ import ../modules
    ++ modules;
  };
  cfg = evaluated.config;
  failed = map (check: check.message) (lib.filter (check: !check.assertion) cfg.assertions);
  selected = values: builtins.attrNames (lib.filterAttrs (_: value: value.enable) values);
  setting = value: if value.enable then builtins.removeAttrs value [ "enable" ] else null;
  host = {
    name = cfg.networking.hostname.name;
    system = cfg.nixpkgs.hostPlatform;
    platform = cfg.deployment.platform;
    deployment = builtins.removeAttrs cfg.deployment [ "platform" ];
    hardware = {
      graphics = cfg.hardware.graphics;
      openrazer = cfg.hardware.openrazer.enable && cfg.desktop.enable;
      initramfsModules = cfg.hardware.initramfs.modules;
      initramfsImages = cfg.hardware.initramfs.images;
    };
    sysctl = lib.filterAttrs (_: value: value != null) cfg.boot.kernel.sysctl;
    # Feature interfaces add cross-field validation and derived values.
    ai = import ../modules/ai/interface.nix {
      inherit lib;
      raw = cfg.programs.ai;
    };
    virtualization = cfg.virtualization;
    systemSettings = import ./system-settings.nix {
      inherit lib;
      raw = {
        hostname.enable = cfg.networking.hostname.enable;
        firewall = setting cfg.networking.firewall;
        hotspot = if cfg.networking.networkmanager.enable then setting cfg.networking.hotspot else null;
        locale = setting cfg.i18n;
        timeZone = if cfg.time.enable then cfg.time.timeZone else null;
        console = setting cfg.console;
        timeSync = setting cfg.services.timesyncd;
        journal = setting cfg.services.journald;
        power = setting cfg.services.logind;
        trim = if cfg.services.fstrim.enable then { enable = true; } else null;
      };
    };
    gitlabRunners = lib.mapAttrs (_: value: builtins.removeAttrs value [ "enable" ]) (
      lib.filterAttrs (
        _: value: cfg.services.gitlabRunner.enable && value.enable
      ) cfg.services.gitlabRunner.instances
    );
    personalAgent.enable = cfg.services.personalAgent.enable;
    powerpanel = cfg.services.powerpanel;
    arch = cfg.arch;
    users = lib.mapAttrs (
      name: user:
      (builtins.removeAttrs user [ "home" ])
      // {
        profiles = selected user.profiles;
        modules = lib.optionals cfg.desktop.enable (selected user.modules);
        homeConfig = user.home;
      }
    ) cfg.users.users;
  };
  capabilities = {
    inherit (cfg) desktop programs;
    networking = cfg.networking.networkmanager.enable;
    bluetooth = cfg.hardware.bluetooth.enable;
    power = cfg.services.powerProfilesDaemon.enable;
    tailscale = cfg.services.tailscale.enable;
    initramfs = cfg.hardware.initramfs.enable;
  };
in
{
  inherit (evaluated) options config;
  inherit capabilities;
  # Home Manager modules can contain recursive package sets. Their own evaluator
  # checks those definitions; force only the serializable Host interface here.
  host =
    if failed != [ ] then
      throw ("invalid configuration:\n" + lib.concatMapStrings (message: "- ${message}\n") failed)
    else
      builtins.deepSeq (
        host // { users = lib.mapAttrs (_: user: builtins.removeAttrs user [ "homeConfig" ]) host.users; }
      ) host;
}
