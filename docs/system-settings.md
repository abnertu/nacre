# System settings

`configuration.nix` selects which native system features are managed. `platforms/arch/system/` owns locale, timezone, firewall and similar settings; `platforms/arch/core/` owns the remaining core files, units, groups and kernel parameters. Each adapter reads one Nix-generated manifest, so convergence and purge cover the same declarations. Before writing or starting anything, adapters check the live files, ownership, native commands and units. These `/etc` files do not belong to Home Manager.

| Option | Manages |
| --- | --- |
| `i18n`, `time`, `console` | Locale, timezone, keymap and font |
| `networking.hostname`, `networking.firewall`, `networking.hotspot` | Hostname, UFW, an existing NetworkManager AP |
| `services.timesyncd`, `services.journald`, `services.logind`, `services.fstrim`, `services.powerpanel` | systemd native settings, UPS daemon config and service state |

System preflight is part of the core stage: a missing hotspot interface, missing resources, conflicts with another provider or owner, and command failures stop the run instead of skipping. Before enabling a feature the first time, check its current owner from a local session you can recover from, especially time sync, storage discard, console resources, NetworkManager and UFW (`sudo ufw status verbose`).

See [hotspot](hotspot.md) for adopting an AP. Disabling a declaration withdraws management only. `purge` removes only the drop-ins this adapter owns and keeps the current locale, timezone, hostname, console, firewall rules and hotspot settings.

## PowerPanel (CyberPower UPS)

`services.powerpanel` manages the UPS through `/etc/pwrstatd.conf`, the AUR package `powerpanel` and `pwrstatd.service`:

- Shutdown on power failure waits for the remaining runtime threshold (`powerfailShutdown = false`, `runtimeThreshold = 300`, `lowbattShutdown = true`).
- The deployment user joins the `power` group, so `pwrstat -status` and `pwrstat -config` work without root.
- A change to `/etc/pwrstatd.conf` records a pending marker and restarts a running `pwrstatd.service`.

## Changes and recovery

Adapters compare content, ownership and mode, and replace a file atomically only when it differs. A pending marker in `/var/lib/nix-config/arch/` is recorded before a change and cleared after it succeeds. Healthy reruns rewrite nothing and restart nothing. logind changes take effect at the next boot instead of restarting the logged-in session. The TRIM timer keeps the native schedule with catch-up disabled; a conflicting schedule needs a manual decision.

On failure, fix the reported cause and rerun with the marker in place. `nacre --verbose switch` shows native commands and diagnostics.

Validate source only:

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.system-settings-interface \
  .#checks.x86_64-linux.system-settings-tests \
  .#checks.x86_64-linux.core-tests \
  .#checks.x86_64-linux.arch-switch-tests \
  .#checks.x86_64-linux.system-firewall-integration
```
