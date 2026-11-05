{ lib }:
let
  # An enable option that defaults to true.
  enabledByDefault =
    description:
    lib.mkEnableOption description
    // {
      default = true;
    };
in
{
  enable = enabledByDefault "virtualization";
  kvm.enable = enabledByDefault "KVM virtual machines through libvirt and QEMU";
  kvm.gui.enable = enabledByDefault "virt-manager with local libvirt management";
  podman.enable = enabledByDefault "rootless Podman containers";
}
