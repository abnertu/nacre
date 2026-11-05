{ lib }:
let
  inherit (lib) mkOption types;
  nullable =
    type:
    mkOption {
      type = types.nullOr type;
      default = null;
    };
  inherit (types) enum;
  bounded = low: high: types.ints.between low high;
  token = types.strMatching "[a-zA-Z0-9_+-]+";
  localeName = enum [
    "en_US.UTF-8"
    "zh_TW.UTF-8"
  ];
  section = options: types.submodule { inherit options; };
  port = bounded 1 65535;
  octet = "(0|[1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])";
in
{
  locale = nullable (section {
    generated = mkOption { type = types.nonEmptyListOf localeName; };
    lang = mkOption { type = localeName; };
  });
  timeZone = nullable (types.strMatching "[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*");
  hostname.enable = lib.mkEnableOption "realizing Host identity as the static hostname";
  timeSync = nullable (section {
    provider = mkOption {
      type = enum [ "systemd-timesyncd" ];
      default = "systemd-timesyncd";
    };
    servers = mkOption {
      type = types.listOf (types.strMatching "[A-Za-z0-9][A-Za-z0-9.:-]*");
      default = [ ];
    };
  });
  journal = nullable (section {
    storage = mkOption {
      type = enum [
        "auto"
        "persistent"
        "volatile"
      ];
    };
    systemMaxUseMiB = nullable (bounded 1 1048576);
    systemKeepFreeMiB = nullable (bounded 1 1048576);
    runtimeMaxUseMiB = nullable (bounded 1 1048576);
    maxRetentionDays = nullable (bounded 1 3650);
  });
  console = nullable (section {
    keymap = mkOption { type = token; };
    font = nullable token;
  });
  power = nullable (section {
    powerKey = nullable (enum [
      "ignore"
      "poweroff"
      "suspend"
    ]);
    lidSwitch = nullable (enum [
      "ignore"
      "suspend"
    ]);
  });
  trim = nullable (section {
    enable = mkOption {
      type = enum [ true ];
      default = true;
    };
  });
  hotspot = nullable (section {
    connection = mkOption { type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9 _.-]*"; };
    ssid = mkOption { type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9 _.-]{0,31}"; };
    interface = mkOption { type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}"; };
    uplink = mkOption { type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}"; };
    band = mkOption {
      type = enum [
        "a"
        "bg"
      ];
      default = "a";
    };
    channel = mkOption { type = bounded 1 196; };
    address = mkOption {
      type = types.strMatching "${octet}\\.${octet}\\.${octet}\\.${octet}/([1-9]|[12][0-9]|30)";
    };
    autoconnect = mkOption {
      type = types.bool;
      default = true;
    };
    ipv6 = mkOption {
      type = enum [
        "shared"
        "disabled"
      ];
      default = "shared";
    };
  });
  firewall = nullable (section {
    provider = mkOption {
      type = enum [ "ufw" ];
      default = "ufw";
    };
    incoming = mkOption {
      type = enum [ "deny" ];
      default = "deny";
    };
    outgoing = mkOption {
      type = enum [ "allow" ];
      default = "allow";
    };
    routed = mkOption {
      type = enum [ "deny" ];
      default = "deny";
    };
    logging = mkOption {
      type = enum [
        "off"
        "low"
        "medium"
        "high"
        "full"
      ];
      default = "low";
    };
    rules = mkOption {
      type = types.listOf (section {
        protocol = mkOption {
          type = enum [
            "tcp"
            "udp"
          ];
        };
        fromPort = mkOption { type = port; };
        toPort = nullable port;
      });
      default = [ ];
    };
  });
}
