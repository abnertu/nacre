# Arch packages of each virtualization component.
{
  kvm = [
    "qemu-desktop"
    "edk2-ovmf"
  ];
  gui = [
    "dnsmasq"
    "nftables"
    "virt-manager"
    "libvirt"
  ];
  podman = [
    "podman"
    "netavark"
    "aardvark-dns"
    "passt"
    "fuse-overlayfs"
    "shadow"
  ];
}
