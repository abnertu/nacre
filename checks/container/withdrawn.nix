# The container configuration with some declarations withdrawn: the
# container test deploys it after the full one and checks the host returns.
{ lib, ... }:
{
  systemd.services.nacre-demo.enable = false;
  environment.etc."nacre-container-test.conf".enable = false;
  services.journald.enable = false;
  boot.kernel.sysctl."net.ipv4.ip_forward" = lib.mkForce null;
}
