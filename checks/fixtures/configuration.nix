# Independent source fixture: do not import the operator's configuration entry.
{ lib, ... }:
{
  networking.hostname.name = lib.mkDefault "fixture";
  # Opt in to every feature so checks can switch each one off.
  networking.hotspot = lib.mapAttrs (_: lib.mkDefault) {
    enable = true;
    connection = "fixture-ap";
    ssid = "Fixture";
    interface = "wifi0";
    uplink = "eth0";
    channel = 36;
    address = "192.0.2.1/24";
  };
  deployment.username = "fixture";
  hardware.initramfs.images = [ "/boot/initramfs-linux.img" ];
  services.powerpanel.enable = lib.mkDefault true;
  hardware.openrazer.enable = lib.mkDefault true;
  # A machine-provided adapter, as machine flakes add through arch.extensions.
  arch.extensions.fixture = {
    label = "fixture-extension";
    adapter = ./extension/adapter.py;
    manifest.greeting = "fixture";
    ownedUnits = [
      {
        unit = "fixture-extension.service";
        path = "/etc/systemd/system/fixture-extension.service";
      }
    ];
  };
  programs.ai.llama = {
    enable = lib.mkDefault true;
    model = {
      device = "ROCm0";
      contextSize = 4096;
    };
  };
  users.users.fixture = {
    description = "Fixture login";
    homeDirectory = "/home/fixture";
    stateVersion = "26.05";
    admin = true;
    homeModules = [ ./home.nix ];
  };
}
