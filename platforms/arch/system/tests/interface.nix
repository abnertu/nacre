{ lib, pkgs }:
let
  parse = raw: import ../../../../lib/system-settings.nix { inherit lib raw; };
  ap = {
    connection = "fixture";
    ssid = "Fixture";
    interface = "wifi0";
    uplink = "eth0";
    channel = 36;
    address = "192.0.2.1/24";
  };
  valid = raw: (builtins.tryEval (builtins.deepSeq (parse raw) true)).success;
  optional = import ../default.nix {
    inherit lib pkgs;
    hostName = "fixture";
    config = parse {
      timeSync.servers = [ "ntp.example.test" ];
      journal = {
        storage = "persistent";
        systemMaxUseMiB = 1024;
        maxRetentionDays = 30;
      };
      power.powerKey = "ignore";
    };
  };

in
assert optional.files.timesyncd == "[Time]\nNTP=ntp.example.test\n";
assert
  optional.files.journald
  == "[Journal]\nMaxRetentionSec=30day\nStorage=persistent\nSystemMaxUse=1024M\n";
assert optional.files.logind == "[Login]\nHandlePowerKey=ignore\n";
assert optional.trimDropin == "[Timer]\nPersistent=false\n";
assert valid { hotspot = ap; };
assert lib.all (override: !(valid { hotspot = ap // override; })) [
  { password = "forbidden-fixture-field"; }
  { address = "999.0.2.1/24"; }
  { address = "192.0.2.0/24"; }
  { address = "192.0.2.255/24"; }
  { address = "192.0.2.1/32"; }
  { interface = "../bad"; }
  { uplink = "wifi0"; }
  { band = "bg"; }
];
assert valid { };
assert (parse { }).locale == null && (parse { }).firewall == null;
assert valid {
  locale = {
    generated = [ "en_US.UTF-8" ];
    lang = "en_US.UTF-8";
  };
};
assert valid {
  timeSync = { };
  journal.storage = "auto";
  console.keymap = "us";
  power.powerKey = "ignore";
  trim = { };
};
assert lib.all (value: !(valid value)) [
  { unknown = true; }
  {
    locale = {
      generated = [ "en_US.UTF-8" ];
      lang = "zh_TW.UTF-8";
    };
  }
  {
    locale = {
      generated = [ "C" ];
      lang = "C";
    };
  }
  { timeZone = "../../secret"; }
  { timeZone = "/etc/localtime"; }
  { timeZone = "Asia/Taipei\n"; }
  { timeSync.provider = "chrony"; }
  { timeSync.servers = [ "$(secret)" ]; }
  {
    journal = {
      storage = "auto";
      systemMaxUseMiB = 0;
    };
  }
  {
    journal = {
      storage = "auto";
      maxRetentionDays = -1;
    };
  }
  { console.keymap = "../us"; }
  { power = { }; }
  { trim.enable = false; }
  {
    firewall.rules = [
      {
        protocol = "tcp";
        fromPort = 0;
      }
    ];
  }
  {
    firewall.rules = [
      {
        protocol = "tcp";
        fromPort = 22;
        toPort = 1;
      }
    ];
  }
  { firewall.incoming = "allow"; }
  { firewall.command = "ufw reset"; }
];
true
