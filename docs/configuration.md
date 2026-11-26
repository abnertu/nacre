# Configuration

A machine flake calls `nacre.lib.mkFlake` with its modules. Installation starts with one `configuration.nix`. Imported machine files can define baselines with `lib.mkDefault`. Ordinary definitions override those baselines regardless of import order. Unknown options, wrong types and invalid combinations fail during evaluation.

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

`runner` enables GitLab Runner and Podman, with desktop and KVM tools disabled. Declare public instance files before building this role. Read the [Runner guide](gitlab-runner.md#runner-role) for installation.

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

When you disable an Arch feature, Nacre keeps its packages, services, registrations and data. It withdraws the feature's [files under /etc](#files-under-etc). Home Manager still activates the newly declared home.

`packages.hold = [ "ghostty" ];` excludes installed packages from Nacre's pacman and AUR upgrades. Missing held packages still install. Dependency resolution can fail if another package needs a newer version. Manual pacman operations ignore this declaration. Remove the hold to resume upgrades.

Kernel defaults support container networking. You can change them in these ways:

- Override a sysctl key.
- Set a key to `null` to withdraw management.
- Replace the module list with `lib.mkForce`.

## Files under /etc

`environment.etc.<name>` declares a text file under `/etc`. The name is relative to `/etc`:

```nix
environment.etc."sudoers.d/50-alice" = {
  text = "alice ALL=(ALL) NOPASSWD: /usr/bin/systemctl\n";
  mode = "0440";
};
environment.etc."ssh/sshd_config.d/50-local.conf".source = ./files/sshd-local.conf;
```

| Option | Behavior |
| --- | --- |
| `text`, `source` | The content. A definition with a higher priority wins. Equal priorities fail evaluation. |
| `mode` | Octal mode, `0644` by default. |
| `group` | Owning group, `root` by default. The owner is always root. |
| `adopt` | Replace an existing file that differs. Nacre saves the original. |
| `enable` | Set it to `false` to withdraw the file. |

Never put secrets in an entry. Its text lands in the Nix store and the deployment manifest.

Prefer a drop-in directory, such as `sshd_config.d`, to a whole file. A drop-in needs no adoption.

Nacre records each file that it writes. These rules apply:

- A file that Nacre created goes away when its declaration goes away.
- An adopted file gets its original back when its declaration goes away.
- An existing file that differs stops preflight until you set `adopt = true`. An identical file is adopted without it.
- A declared file that someone edited is written again.
- A withdrawn file that someone edited stops the deployment. Restore or delete it, or run `nacre forget file:<name>` to leave it unmanaged.

Built-in files use the same option. Override the NetworkManager files with a plain definition or `lib.mkDefault`. The kernel module, sysctl and PowerPanel files come from their typed options. Change `boot.kernelModules`, `boot.kernel.sysctl` or `services.powerpanel` instead.

Evaluation rejects absolute names, `.` and `..` components, nested entries and paths that another owner writes. The system settings, AI, the repository, managed blocks and account databases own reserved paths. An extension reserves the paths that its adapter writes with `arch.extensions.<name>.reservedPaths`.

Read [local AI](ai.md) before you select models, offload or context under `programs.ai.llama.models`.
Read [GitLab Runner](gitlab-runner.md) before you declare instances under `services.gitlabRunner`.

## Users and homes

`deployment.username` selects an existing login account declared in `users.users`. To select another user, change both declarations. Modules create their service accounts without home composition. Keep Home Manager's `stateVersion` fixed during routine updates.

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

Nacre uses `lib.mkDefault` for these defaults, so plain home definitions win. Keep the reviewed Noctalia snapshot at `homes/<user>/noctalia/config.toml`. The CLI and `checkhealth` look for it there.

After you edit, run `nacre build`. Then review `nacre plan`.

## Machine extensions

Features and machine modules contribute native resources through `arch`. A machine can add packages, groups and units through `arch.pacman`, `arch.aur`, `arch.groups`, `arch.systemUnits` and `arch.userServices`. Register privileged adapters under `arch.extensions`:

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

Set `arch.extensions.<name>.purge = true` when the adapter owns additional retirement work. The default is false. Explicit purge invokes opted-in adapters before built-in retirement, in extension-name order. It does not check preparation readiness or dependencies. Every failure, including exit 20, stops purge. Keep system-unit retirement in `ownedUnits`. Disabling or removing an extension withdraws management without invoking its purge hook.

Pass external inputs into the module from the `flake.nix` of the machine. `extraOutputs` exposes additional packages, apps and checks:

```nix
outputs = { nacre, my-service, ... }: nacre.lib.mkFlake {
  modules = [ ./configuration.nix (import ./modules/my-service.nix { inherit my-service; }) ];
  extraOutputs.packages.x86_64-linux.my-service = my-service.packages.x86_64-linux.default;
};
```
