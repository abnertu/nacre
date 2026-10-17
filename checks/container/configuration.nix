# Container smoke-test overrides: withdraw what a rootless container lacks.
{ config, lib, ... }:
{
  networking.hotspot.enable = false;
  hardware.bluetooth.enable = false;
  hardware.initramfs.enable = false;
  # systemd skips both units under ConditionVirtualization=!container.
  services.timesyncd.enable = false;
  services.fstrim.enable = false;
  services.gitlabRunner.enable = false;
  # Not namespaced: a container network namespace has no such key.
  boot.kernel.sysctl."net.core.default_qdisc" = lib.mkForce null;
  # Local worktrees do not exist inside the container.
  users.users.${config.deployment.username}.development = lib.mkForce {
    neovimPath = null;
    hyprlandPath = null;
  };
}
