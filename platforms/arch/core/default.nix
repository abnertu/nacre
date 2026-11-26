# Core native policy for the privileged core adapter. One manifest drives
# preflight, convergence and purge, so purge always matches what is managed.
{
  lib,
  pkgs,
  username,
  deploymentUser,
  hardware,
  capabilities,
  arch,
  sysctl ? { },
  kernelModules ? [ ],
  nixSettings ? { },
  ownedUnits ? [ ],
}:
let
  files = ../files;
  read = name: builtins.readFile (files + "/${name}");
  # environment.etc entries, merged by platforms/arch/module.nix.
  inherit (arch) etc;
  repository =
    if arch.lizardbyte == [ ] then
      null
    else
      {
        name = "lizardbyte";
        path = "/etc/pacman.d/nix-config-lizardbyte.conf";
        text = read "pacman-lizardbyte.conf";
        source = "${files}/pacman-lizardbyte.conf";
        include = "Include = /etc/pacman.d/nix-config-lizardbyte.conf";
      };
  nixBlock = {
    path = "/etc/nix/nix.conf";
    name = "settings";
    # Marks a host whose deployment keeps receipts (core/receipts.py RECEIPT_LINE).
    text =
      "# nix-config receipts 1\n"
      + lib.concatStrings (
        lib.mapAttrsToList
          (
            key: value:
            let
              rendered =
                if builtins.isList value then
                  lib.concatStringsSep " " value
                else if builtins.isBool value then
                  lib.boolToString value
                else
                  toString value;
            in
            "${key} = ${rendered}\n"
          )
          (
            nixSettings
            // {
              trusted-users = [
                "root"
                "@wheel"
                username
              ];
            }
          )
      );
    action = "nix-daemon";
    create = true;
  };
  initramfsBlock = {
    path = "/etc/mkinitcpio.conf";
    name = "modules";
    text = "MODULES+=(${lib.concatMapStrings (module: " ${module}") hardware.initramfsModules} )\n";
    action = "initramfs";
    create = false;
  };
  manifest = {
    user = username;
    inherit etc;
    inherit repository;
    inherit (arch) units;
    blocks = lib.optional capabilities.initramfs initramfsBlock ++ [ nixBlock ];
    initramfsImages = lib.optionals capabilities.initramfs hardware.initramfsImages;
    groups = lib.unique (
      arch.groups ++ deploymentUser.groups ++ lib.optional deploymentUser.admin "wheel"
    );
    # The nix.conf block restarts nix-daemon; units restart by their triggers.
    restarts = [
      {
        action = "nix-daemon";
        unit = "nix-daemon.service";
        onlyIfActive = false;
      }
    ];
    inherit kernelModules;
    sysctl = lib.mapAttrs (_: toString) sysctl;
    fileCapabilities =
      lib.optional (capabilities.desktop.enable && capabilities.programs.sunshine.enable)
        {
          path = "/usr/bin/sunshine";
          capability = "cap_sys_admin=p";
        };
    purge = {
      # Initramfs modules stay: withdrawing them would require new boot images.
      blocks = [ nixBlock ];
      # Units of machine-provided extensions, retired after their adapters purge.
      inherit ownedUnits;
    };
  };
in
{
  inherit manifest;
  manifestFile = pkgs.writeText "arch-core.json" (builtins.toJSON manifest);
}
