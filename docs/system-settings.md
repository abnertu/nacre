# Arch system settings

`configuration.nix` selects native system capabilities; `platforms/arch/system/` reconciles them, and `platforms/arch/core/` owns the remaining core files, units, groups and kernel runtime values. Each adapter reads one Nix-generated manifest, so convergence and purge cover the same declarations. Nix generates fixed systemd drop-in content, including the fstrim timer policy. The Python adapter checks the live filesystem, ownership, native commands and units before writing or starting anything. Home Manager does not own these `/etc` files.

| Public area | Native responsibility |
| --- | --- |
| `i18n`, `time`, `console` | Locale, timezone, keymap and font |
| `networking.hostname`, `networking.firewall`, `networking.hotspot` | Host identity, UFW and prepared NetworkManager AP |
| `services.timesyncd`, `services.journald`, `services.logind`, `services.fstrim`, `services.powerpanel` | Native systemd policy, UPS daemon configuration, and service state |

System preflight is a core stage. Missing declared hotspot interfaces, unavailable assets, conflicting providers or ownership, and failed commands stop deployment; they are not optional skips. Before first enabling a capability, inspect current ownership from a local recovery-capable session. In particular, review time providers, storage discard, console assets, NetworkManager and UFW. For firewall policy:

```bash
sudo ufw status verbose
```

See [hotspot](hotspot.md) for AP adoption. A disabled declaration withdraws management but does not automatically remove existing native files, accounts, packages or service state.

### PowerPanel (CyberPower UPS)

`services.powerpanel` manages CyberPower UPS control via `/etc/pwrstatd.conf`, the `powerpanel` AUR package, and `pwrstatd.service`.
- Auto-shutdown upon outage is based on Remaining Runtime (`powerfailShutdown = false`, `runtimeThreshold = 300`, `lowbattShutdown = true`), avoiding shutting down immediately on power failure.
- The deployment user is automatically added to the `power` login group, allowing non-root execution of `pwrstat -status` and `pwrstat -config`.
- Changes to `/etc/pwrstatd.conf` record a pending marker and automatically restart `pwrstatd.service`.

## Changes and recovery

The adapter checks file content, ownership and mode, then uses atomic replacement when a managed file actually differs. It records pending actions under `/var/lib/nix-config/arch/` before mutations and clears each marker only after the associated action succeeds. A healthy rerun neither rewrites identical files nor restarts healthy services. Logind changes wait for a boot boundary instead of restarting active login sessions. The TRIM timer keeps the native schedule and disables catch-up; conflicting timing overrides require operator review.

After a failure, correct the reported cause and rerun with markers intact. `just arch-workstation verbose` shows native commands and captured diagnostics; failures retain stdout, stderr and partial timeout output. Never include protected credentials or unrelated application data in a report.

Source-only validation:

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.system-settings-interface \
  .#checks.x86_64-linux.system-settings-tests \
  .#checks.x86_64-linux.core-tests \
  .#checks.x86_64-linux.arch-switch-tests \
  .#checks.x86_64-linux.system-firewall-integration
```

These checks use temporary roots, fake commands and an isolated VM. Full repository validation is `just check`.
