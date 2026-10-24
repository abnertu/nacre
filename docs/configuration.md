# Configuration

A machine flake calls `nacre.lib.mkFlake` with its modules. Installation starts with one `configuration.nix`. Imported machine files can define baselines with `lib.mkDefault`. Ordinary definitions override those baselines, in each import order. Unknown options, wrong types and invalid combinations fail during evaluation.

```nix
{ ... }:
{
  imports = [ ./hosts/box ];
  networking.firewall.enable = false;
  services.fstrim.enable = false;
  time.timeZone = "UTC";
}
```

Before you build, inspect the normalized policy:

```bash
nix eval .#lib.configuration.networking.hostname.name
nix eval --json .#lib.configuration.networking.firewall
```

## Roles

`minimal` supplies the core system, shell and development tools. `workstation`, the default, adds Hyprland, Sunshine, Vesktop and Vicinae. Role baselines yield to machine defaults and ordinary overrides.

A deployment has the name `<hostname>-<role>`. It is also available as `#deployment`.

## Options

| Change | Namespace |
| --- | --- |
| Network, AP, firewall, hostname | `networking` |
| Locale, timezone, console | `i18n`, `time`, `console` |
| Native services and AI | `services`, `programs.ai` |
| Hardware and virtualization | `hardware`, `virtualization` |
| Kernel modules and sysctl | `boot.kernelModules`, `boot.kernel.sysctl` |
| Managed Nix daemon block | `nix.settings` |
| Additional native packages | `packages.extra.pacman`, `packages.extra.aur` |
| Held upgrades | `packages.hold` |
| Desktop and home programs | `desktop`, `programs`, `users.users.<name>.home` |

When you disable an Arch feature, Nacre withdraws management. It does not remove the packages, services, registrations or data of the feature. Home Manager still activates the newly declared home.

`packages.hold = [ "ghostty" ];` excludes installed packages from Nacre's pacman and AUR upgrades. Missing held packages still install. Dependency resolution can fail if another package needs a newer version. Manual pacman operations ignore this declaration. Remove the hold to resume upgrades.

Kernel defaults support container networking. You can change them in these ways:

- Override a sysctl key.
- Set a key to `null` to withdraw management.
- Replace the module list with `lib.mkForce`.

Read [local AI](ai.md) before you select models, offload or context under `programs.ai.llama.models`.

## Users and homes

`deployment.username` selects an existing login account declared in `users.users`. To change the user, change both. Modules create their service accounts without home composition. Keep Home Manager's `stateVersion` fixed during routine updates.

Shared profiles provide shell, development tools, themes and default application configuration. Personal settings belong in machine-owned home modules:

```nix
users.users.alice.homeModules = [ ./homes/alice/home.nix ];
```

```nix
# homes/alice/home.nix
{
  programs.git.settings.user.name = "Alice";
  xdg.configFile.ghostty = {
    source = ./files/ghostty;
    recursive = true;
  };
}
```

Nacre uses `lib.mkDefault` for these defaults, so plain home definitions win. Keep the reviewed Noctalia snapshot at `homes/<user>/noctalia/config.toml`. The CLI and doctor look for it there.

After you edit, run `nacre build`. Then review `nacre plan`.

## Machine extensions

A machine can add packages, groups and units through `arch.pacman`, `arch.aur`, `arch.groups`, `arch.systemUnits` and `arch.userServices`. Register privileged adapters under `arch.extensions`:

```nix
{ my-service }:
{ config, lib, ... }:
{
  options.services.myService.enable = lib.mkEnableOption "my service";
  config = lib.mkIf config.services.myService.enable {
    arch.pacman = [ "podman" ];
    arch.extensions.my-service = {
      label = "my-service";
      adapter = ./adapter.py;
      manifest.executable = "${my-service.packages.x86_64-linux.default}/bin/my-service";
      requires = [ "ai" ];
      notReady = "run my-service-setup first";
      ownedUnits = [ {
        unit = "my-service.service";
        path = "/etc/systemd/system/my-service.service";
      } ];
    };
  };
}
```

Nacre invokes `adapter MANIFEST PHASE` as root for `preflight`, `plan` and `converge`. Exit 20 means preparation has never completed. [nix-adapter](https://github.com/abnertu/nix-adapter) provides the base adapter classes. Extensions converge after built-in optional modules. Purge retires their declared `ownedUnits`.

Pass external inputs into the module from the `flake.nix` of the machine. `extraOutputs` exposes additional packages, apps and checks:

```nix
outputs = { nacre, my-service, ... }: nacre.lib.mkFlake {
  modules = [ ./configuration.nix (import ./modules/my-service.nix { inherit my-service; }) ];
  extraOutputs.packages.x86_64-linux.my-service = my-service.packages.x86_64-linux.default;
};
```
