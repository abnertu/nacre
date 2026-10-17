{ lib, ... }:
{
  i18n.generated = lib.mkDefault [
    "en_US.UTF-8"
    "zh_TW.UTF-8"
  ];
  time.timeZone = lib.mkDefault "Asia/Taipei";
  networking.hotspot = lib.mapAttrs (_: lib.mkDefault) {
    enable = true;
    connection = "Arch-Hyprland";
    ssid = "Arch-Hyprland";
    interface = "wlp15s0";
    uplink = "enp14s0";
    band = "a";
    channel = 157;
    address = "192.168.10.1/24";
    autoconnect = true;
    ipv6 = "shared";
  };
  networking.firewall.rules = lib.mkDefault [
    {
      protocol = "tcp";
      fromPort = 7777;
    }
    {
      protocol = "udp";
      fromPort = 7777;
    }
    {
      protocol = "tcp";
      fromPort = 47990;
    }
    {
      protocol = "udp";
      fromPort = 27031;
      toPort = 27036;
    }
  ];
}
