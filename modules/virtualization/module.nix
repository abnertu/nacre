# Virtualization: KVM, virt-manager and Podman packages and groups.
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
  };
  config.systemd.units."libvirtd.socket" = lib.mkIf gui { };
  # Container and guest networking: bridges, veth pairs and forwarding.
  config.boot = lib.mkIf cfg.enable {
    kernelModules = lib.mkDefault [
      "bridge"
      "br_netfilter"
      "veth"
    ];
    kernel.sysctl = lib.mapAttrs (_: lib.mkDefault) {
      "net.ipv4.ip_forward" = 1;
      "net.ipv6.conf.all.forwarding" = 1;
      "net.bridge.bridge-nf-call-iptables" = 1;
    };
  };
}
