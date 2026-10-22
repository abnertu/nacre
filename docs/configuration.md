# Configuration

A machine flake calls `nacre.lib.mkFlake` with its modules. Installation starts with one `configuration.nix`; imported machine files may define baselines with `lib.mkDefault`, which ordinary definitions override regardless of import order. Unknown options, wrong types and invalid combinations fail during evaluation.

```nix
{ ... }:
{
  imports = [ ./hosts/box ];
  networking.firewall.enable = false;
  services.fstrim.enable = false;
  time.timeZone = "UTC";
}
```

Inspect normalized policy before building:

```bash
nix eval .#lib.configuration.networking.hostname.name
nix eval --json .#lib.configuration.networking.firewall
```

## Roles

`minimal` supplies the core system, shell and development tools. `workstation`, the default, adds Hyprland, Sunshine, Vesktop and Vicinae. Role baselines yield to machine defaults and ordinary overrides.

Deployments are named `<hostname>-<role>` and also exposed as `#deployment`.

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

Disabling an Arch feature withdraws management without removing its packages, services, registrations or data. Home Manager still activates the newly declared home.

`packages.hold = [ "ghostty" ];` excludes installed packages from Nacre's pacman and AUR upgrades. Missing held packages still install; dependency resolution can fail if another package requires a newer version. Manual pacman operations do not honor this declaration. Remove the hold to resume upgrades.

Kernel defaults support container networking. Override a sysctl key, set it to `null` to withdraw management, or replace the module list with `lib.mkForce`. Read [local AI](ai.md) before selecting models, offload or context under `programs.ai.llama.models`.

## Users and homes

`deployment.username` selects an existing login account declared in `users.users`. Changing users requires changing both. Modules create their service accounts without home composition. Keep Home Manager's `stateVersion` fixed during routine updates.

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

Nacre uses `lib.mkDefault` for these defaults, so plain home definitions win. Keep the reviewed Noctalia snapshot at `homes/<user>/noctalia/config.toml`, where the CLI and doctor look for it.

After editing, run `nacre build` and review `nacre plan`.

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

Nacre invokes `adapter MANIFEST PHASE` as root for `preflight`, `plan` and `converge`. Exit 20 means preparation has never completed. [nix-adapter](https://github.com/abnertu/nix-adapter) provides the base adapter classes. Extensions converge after built-in optional modules; purge retires their declared `ownedUnits`.

Pass external inputs into the module from the machine's `flake.nix`. `extraOutputs` exposes additional packages, apps and checks:

```nix
outputs = { nacre, my-service, ... }: nacre.lib.mkFlake {
  modules = [ ./configuration.nix (import ./modules/my-service.nix { inherit my-service; }) ];
  extraOutputs.packages.x86_64-linux.my-service = my-service.packages.x86_64-linux.default;
};
```
