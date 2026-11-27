# Container smoke-test overrides: withdraw what a rootless container lacks.
{ config, lib, ... }:
{
  networking.hotspot.enable = false;
  hardware.bluetooth.enable = false;
  hardware.initramfs.enable = false;
  # systemd skips both units under ConditionVirtualization=!container.
  services.timesyncd.enable = false;
  services.fstrim.enable = false;
  # A rootless container cannot load modules; the host may lack them.
  boot.kernelModules = lib.mkForce [ ];
  boot.kernel.sysctl = {
    # Not namespaced: a container network namespace has no such key.
    "net.core.default_qdisc" = lib.mkForce null;
    # Exist only while the host has br_netfilter and tcp_bbr loaded.
    "net.bridge.bridge-nf-call-iptables" = lib.mkForce null;
    "net.ipv4.tcp_congestion_control" = lib.mkForce null;
  };
  # A file under /etc that the withdrawal generation removes again.
  environment.etc."nacre-container-test.conf".text = "declared by the container test\n";
  # A binary file, a link, and a link over an operator link that the
  # script creates with group wheel; withdrawal restores that one.
  environment.etc."nacre-container-blob.bin".source = ./blob.bin;
  environment.etc."nacre-container-link".target = "/usr/share/zoneinfo/UTC";
  environment.etc."nacre-container-adopted" = {
    target = "/usr/share/zoneinfo/Asia/Taipei";
    adopt = true;
  };
  # An authored service: real systemd must load, enable and start it.
  systemd.services.nacre-demo = {
    description = "Nacre container demo";
    serviceConfig.ExecStart = "/usr/bin/sleep infinity";
    wantedBy = [ "multi-user.target" ];
  };
  # Local worktrees do not exist inside the container.
  users.users.${config.deployment.username}.development = lib.mkForce {
    neovimPath = null;
    hyprlandPath = null;
  };
}
