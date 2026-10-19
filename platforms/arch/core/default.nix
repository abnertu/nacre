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
  powerpanel ? null,
  ownedUnits ? [ ],
}:
let
  files = ../files;
  read = name: builtins.readFile (files + "/${name}");
  file = path: text: action: { inherit path text action; };
  managedFiles =
    lib.optionals capabilities.networking (
      [ (file "/etc/NetworkManager/conf.d/main.conf" (read "NetworkManager-main.conf") "network") ]
      ++ lib.optional capabilities.tailscale (
        file "/etc/NetworkManager/conf.d/99-tailscale.conf" (read "NetworkManager-tailscale.conf") "network"
      )
    )
    ++ [
      (file "/etc/modules-load.d/nix-config-podman.conf" (lib.concatMapStrings (
        module: "${module}\n"
      ) kernelModules) null)
      (file "/etc/sysctl.d/99-nix-config.conf" (lib.concatStrings (
        lib.mapAttrsToList (key: value: "${key} = ${toString value}\n") sysctl
      )) null)
    ]
    ++ lib.optional (powerpanel != null && powerpanel.enable) (
      file "/etc/pwrstatd.conf" (builtins.readFile powerpanel.configFile) "pwrstatd"
    )
    ++ lib.optional capabilities.desktop.enable (
      file "/etc/systemd/system/getty@tty1.service.d/override.conf" (lib.replaceStrings
        [ "@USER@" ]
        [ username ]
        (read "tty1-autologin.conf")
      ) "units"
    );
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
    text = lib.concatStrings (
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
    files = managedFiles;
    inherit repository;
    units = arch.systemUnits;
    blocks = lib.optional capabilities.initramfs initramfsBlock ++ [ nixBlock ];
    initramfsImages = lib.optionals capabilities.initramfs hardware.initramfsImages;
    groups = lib.unique (
      arch.groups ++ deploymentUser.groups ++ lib.optional deploymentUser.admin "wheel"
    );
    reloadUnits = capabilities.desktop.enable;
    restarts =
      lib.optional capabilities.networking {
        action = "network";
        unit = "NetworkManager.service";
        onlyIfActive = false;
      }
      ++ [
        {
          action = "nix-daemon";
          unit = "nix-daemon.service";
          onlyIfActive = false;
        }
        {
          action = "pwrstatd";
          unit = "pwrstatd.service";
          onlyIfActive = true;
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
