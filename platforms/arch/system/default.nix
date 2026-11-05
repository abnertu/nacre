# Manifest of the system adapter, built from the native settings of the
# evaluated configuration.
{
  lib,
  pkgs,
  config,
  hostName,
}:
let
  present = value: value != null;
  settings = config // {
    hostname = if config.hostname.enable then hostName else null;
  };
  dropin =
    section: attrs:
    "[${section}]\n"
    + lib.concatStrings (
      lib.mapAttrsToList (key: value: "${key}=${toString value}\n") (lib.filterAttrs (_: present) attrs)
    );
  inherit (config) journal;
  unit = suffix: value: if value == null then null else "${toString value}${suffix}";
  files =
    lib.optionalAttrs (present config.timeSync) {
      "timesyncd" = dropin "Time" (
        lib.optionalAttrs (config.timeSync.servers != [ ]) {
          NTP = lib.concatStringsSep " " config.timeSync.servers;
        }
      );
    }
    // lib.optionalAttrs (present journal) {
      "journald" = dropin "Journal" {
        Storage = journal.storage;
        SystemMaxUse = unit "M" journal.systemMaxUseMiB;
        SystemKeepFree = unit "M" journal.systemKeepFreeMiB;
        RuntimeMaxUse = unit "M" journal.runtimeMaxUseMiB;
        MaxRetentionSec = unit "day" journal.maxRetentionDays;
      };
    }
    // lib.optionalAttrs (present config.power) {
      "logind" = dropin "Login" {
        HandlePowerKey = config.power.powerKey;
        HandleLidSwitch = config.power.lidSwitch;
      };
    };
  trimDropin = "[Timer]\nPersistent=false\n";
  paths = {
    vconsole = "/etc/vconsole.conf";
    localeGen = "/etc/locale.gen";
    localeConf = "/etc/locale.conf";
    localtime = "/etc/localtime";
    hostnameFile = "/etc/hostname";
  };
in
{
  inherit files trimDropin;
  manifest = pkgs.writeText "arch-system-settings.json" (
    builtins.toJSON (settings // { inherit files trimDropin paths; })
  );
}
