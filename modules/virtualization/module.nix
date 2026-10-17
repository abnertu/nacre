{ config, lib, ... }:
let
  cfg = config.virtualization;
  packages = import ./packages.nix;
  kvm = cfg.enable && cfg.kvm.enable;
  gui = kvm && cfg.kvm.gui.enable;
in
{
  options.virtualization = import ./options.nix { inherit lib; };
  config.arch = {
    pacman =
      lib.optionals kvm packages.kvm
      ++ lib.optionals gui packages.gui
      ++ lib.optionals (cfg.enable && cfg.podman.enable) packages.podman;
    groups = lib.optional kvm "kvm";
    systemUnits = lib.optional gui "libvirtd.socket";
  };
}
