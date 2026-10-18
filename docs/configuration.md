# Configuration

A machine's flake passes its modules to `nacre.lib.mkFlake`; `nacre install` writes one with a single `configuration.nix`. In Nacre's own repository, `configuration.nix` overrides the selected host. The imported `hosts/arch` sets defaults with `lib.mkDefault`, so plain definitions in `configuration.nix` win; import order does not matter. Unknown options, wrong types and invalid combinations fail at evaluation.

```nix
{ ... }:
{
  imports = [ ./hosts/arch ];
  networking.firewall.enable = false;
  services.fstrim.enable = false;
  time.timeZone = "UTC";
}
```

Inspect resolved values before building or activating:

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
nix eval --json .#lib.configurations.arch.networking.firewall
```

## Roles

`role` picks the baseline composition:

| Role | Contents |
| --- | --- |
| `minimal` | Core system, shell and development tools; no graphical session |
| `workstation` (default) | `minimal` plus the Hyprland desktop, Sunshine, Vesktop and Vicinae |

Roles sit below host defaults, which sit below `configuration.nix`, so any value a role sets can be overridden. The deployment is named `<hostname>-<role>`, for example `arch-workstation`, and is also available as `#deployment`.

## Where to change things

| Change | Namespace |
| --- | --- |
| Network, hotspot, firewall, hostname | `networking` |
| Locale, timezone, console | `i18n`, `time`, `console` |
| Native services, AI, Runners, Personal Agent | `services`, `programs.ai` |
| Hardware and virtualization | `hardware`, `virtualization` |
| Kernel modules and parameters | `boot.kernelModules`, `boot.kernel.sysctl` |
| Nix daemon settings (`/etc/nix/nix.conf` managed block) | `nix.settings` |
| Packages `update` must not upgrade | `packages.hold` |
| Graphical session and user programs | `desktop`, `programs`, `users.users.<name>.home` |

A top-level switch controls the resources it owns. Disabling an Arch feature withdraws management only: packages, services, registrations and application data stay. Home Manager switches to the new generation as usual.

`packages.hold` keeps installed packages at their version during `update`, for example `packages.hold = [ "kitty" ];` while an upgrade is broken. It works like pacman's `--ignore` for both repository and AUR packages: missing held packages still install, a manual `pacman -Syu` ignores the hold, and an upgrade whose dependencies need a newer held package fails resolution. Remove the entry to resume upgrades.

`boot.kernelModules` and `boot.kernel.sysctl` default to a container networking baseline (bridge modules, forwarding, BBR). Override one key, set it to `null` to withdraw it, or replace the module list with `lib.mkForce`.

AI models are selected under `programs.ai.llama.models.<inventory-key>`; read the [AI guide](ai.md) before changing models, offload or context.

## Users and homes

The host selects an existing login account with `deployment.username`; the account must exist before deployment. To switch users, change both the selected account and its declared identity, starting from [host users](../hosts/arch/users.nix). Shared home behavior belongs in `profiles/` or home modules, per-machine differences in `homes/` or the host. Service accounts belong to their modules and get no home. Keep Home Manager's `stateVersion` fixed through routine updates.

After changes, run `just check-fast`, `just check` and `just build`.
