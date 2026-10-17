{
  graphics = "amd";
  openrazer.enable = true;
  initramfs = {
    modules = [
      "usbhid"
      "xhci_pci"
      "amdgpu"
    ];
    images = [ "/boot/initramfs-linux.img" ];
  };
}
