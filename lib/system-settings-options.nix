# Types of the native settings that the system adapter owns. Each top-level
# attribute is the manifest value of one setting: null leaves the host as it
# is. `lib/configuration-options.nix` exposes the same fields as user options
# through `systemSection`, so the types have this one owner.
{ lib }:
let
  inherit (lib) mkOption types;
  inherit (types) enum;

  bounded = low: high: types.ints.between low high;
  token = types.strMatching "[a-zA-Z0-9_+-]+";
  port = bounded 1 65535;
  octet = "(0|[1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])";
  interfaceName = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}";
  localeName = enum [
    "en_US.UTF-8"
    "zh_TW.UTF-8"
  ];
  mebibytes = bounded 1 1048576;
in
{
  locale = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          generated = mkOption {
            type = types.nonEmptyListOf localeName;
            description = "Locales enabled in the managed block of /etc/locale.gen.";
          };
          lang = mkOption {
            type = localeName;
            description = "LANG in /etc/locale.conf.";
          };
        };
      }
    );
    default = null;
    description = "Generated locales and the system language; null leaves it unmanaged.";
  };

  timeZone = mkOption {
    type = types.nullOr (types.strMatching "[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*");
    default = null;
    description = "Zoneinfo name that /etc/localtime links to; null leaves it unmanaged.";
  };

  hostname.enable = lib.mkEnableOption "realizing Host identity as the static hostname";

  timeSync = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          provider = mkOption {
            type = enum [ "systemd-timesyncd" ];
            default = "systemd-timesyncd";
            description = "Time synchronization service; the only supported one is systemd-timesyncd.";
          };
          servers = mkOption {
            type = types.listOf (types.strMatching "[A-Za-z0-9][A-Za-z0-9.:-]*");
            default = [ ];
            example = [ "time.cloudflare.com" ];
            description = "NTP servers; an empty list keeps the distribution defaults.";
          };
        };
      }
    );
    default = null;
    description = "Network time synchronization; null leaves it unmanaged.";
  };

  journal = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          storage = mkOption {
            type = enum [
              "auto"
              "persistent"
              "volatile"
            ];
            description = "Where the journal keeps logs: on disk, in memory, or on disk when /var/log/journal exists.";
          };
          systemMaxUseMiB = mkOption {
            type = types.nullOr mebibytes;
            default = null;
            description = "Largest disk space, in MiB, that persistent logs may use; null keeps the journald default.";
          };
          systemKeepFreeMiB = mkOption {
            type = types.nullOr mebibytes;
            default = null;
            description = "Disk space, in MiB, that journald leaves free; null keeps the journald default.";
          };
          runtimeMaxUseMiB = mkOption {
            type = types.nullOr mebibytes;
            default = null;
            description = "Largest memory, in MiB, that volatile logs may use; null keeps the journald default.";
          };
          maxRetentionDays = mkOption {
            type = types.nullOr (bounded 1 3650);
            default = null;
            description = "Days after which journald removes old entries; null keeps them until space runs out.";
          };
        };
      }
    );
    default = null;
    description = "systemd-journald storage and retention; null leaves it unmanaged.";
  };

  console = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          keymap = mkOption {
            type = token;
            example = "us";
            description = "KEYMAP in /etc/vconsole.conf; it must exist under the kbd keymaps.";
          };
          font = mkOption {
            type = types.nullOr token;
            default = null;
            example = "ter-v16n";
            description = "FONT in /etc/vconsole.conf; null keeps the kernel font.";
          };
        };
      }
    );
    default = null;
    description = "Virtual console keymap and font; null leaves it unmanaged.";
  };

  power = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          powerKey = mkOption {
            type = types.nullOr (enum [
              "ignore"
              "poweroff"
              "suspend"
            ]);
            default = null;
            description = "Action of the power key; null keeps the logind default.";
          };
          lidSwitch = mkOption {
            type = types.nullOr (enum [
              "ignore"
              "suspend"
            ]);
            default = null;
            description = "Action of closing the lid; null keeps the logind default.";
          };
        };
      }
    );
    default = null;
    description = "systemd-logind power key and lid actions; null leaves it unmanaged.";
  };

  trim = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          enable = mkOption {
            type = enum [ true ];
            default = true;
            description = "Fixed at true: a declared trim setting always manages the timer.";
          };
        };
      }
    );
    default = null;
    description = "The fstrim.timer schedule, with catch-up disabled; null leaves it unmanaged.";
  };

  hotspot = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          connection = mkOption {
            type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9 _.-]*";
            description = "Name of the prepared NetworkManager connection.";
          };
          ssid = mkOption {
            type = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9 _.-]{0,31}";
            description = "Network name that the access point broadcasts.";
          };
          interface = mkOption {
            type = interfaceName;
            example = "wlan0";
            description = "Wireless interface that runs the access point.";
          };
          uplink = mkOption {
            type = interfaceName;
            example = "eth0";
            description = "Interface whose connection the access point shares.";
          };
          band = mkOption {
            type = enum [
              "a"
              "bg"
            ];
            default = "a";
            description = "Wi-Fi band: a for 5 GHz, bg for 2.4 GHz.";
          };
          channel = mkOption {
            type = bounded 1 196;
            description = "Wi-Fi channel within the chosen band.";
          };
          address = mkOption {
            type = types.strMatching "${octet}\\.${octet}\\.${octet}\\.${octet}/([1-9]|[12][0-9]|30)";
            example = "10.42.0.1/24";
            description = "IPv4 address and prefix of the access point on its interface.";
          };
          autoconnect = mkOption {
            type = types.bool;
            default = true;
            description = "Whether NetworkManager starts the access point at boot.";
          };
          ipv6 = mkOption {
            type = enum [
              "shared"
              "disabled"
            ];
            default = "shared";
            description = "IPv6 method of the access point: shared with clients, or off.";
          };
        };
      }
    );
    default = null;
    description = "A NetworkManager access point that already exists; null leaves it unmanaged.";
  };

  firewall = mkOption {
    type = types.nullOr (
      types.submodule {
        options = {
          provider = mkOption {
            type = enum [ "ufw" ];
            default = "ufw";
            description = "Firewall manager; the only supported one is UFW.";
          };
          incoming = mkOption {
            type = enum [ "deny" ];
            default = "deny";
            description = "Fixed default policy for incoming traffic.";
          };
          outgoing = mkOption {
            type = enum [ "allow" ];
            default = "allow";
            description = "Fixed default policy for outgoing traffic.";
          };
          routed = mkOption {
            type = enum [ "deny" ];
            default = "deny";
            description = "Fixed default policy for forwarded traffic.";
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
            description = "UFW logging level.";
          };
          rules = mkOption {
            type = types.listOf (
              types.submodule {
                options = {
                  protocol = mkOption {
                    type = enum [
                      "tcp"
                      "udp"
                    ];
                    description = "Transport protocol that the rule allows.";
                  };
                  fromPort = mkOption {
                    type = port;
                    description = "Allowed port, or the first port of an allowed range.";
                  };
                  toPort = mkOption {
                    type = types.nullOr port;
                    default = null;
                    description = "Last port of an allowed range; null allows fromPort alone.";
                  };
                };
              }
            );
            default = [ ];
            example = [
              {
                protocol = "tcp";
                fromPort = 22;
              }
            ];
            description = "Incoming ports to allow on every interface; Nacre owns these rules only.";
          };
        };
      }
    );
    default = null;
    description = "UFW policy and incoming rules; null leaves it unmanaged.";
  };
}
