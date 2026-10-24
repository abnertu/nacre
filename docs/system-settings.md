# System settings

The system adapter owns locale, timezone, console, hostname, firewall, hotspot and selected native service settings. Core adapters own the remaining native files, units, groups and kernel parameters. Their Nix-generated manifests define both convergence and purge. Home Manager does not own these `/etc` files.

| Options | Native resources |
| --- | --- |
| `i18n`, `time`, `console` | Locale, timezone, keymap and font |
| `networking.hostname`, `networking.firewall`, `networking.hotspot` | Hostname, UFW and an existing NetworkManager AP |
| `services.timesyncd`, `services.journald`, `services.logind`, `services.fstrim`, `services.powerpanel` | Native settings, service state and UPS configuration |

Preflight checks files, ownership, commands and units before mutations. Missing interfaces or resources, conflicting providers and failed queries stop the core stage. Before the first adoption, inspect the current ownership from a recoverable local session. Examine UFW, networking, time sync, storage discard and console settings carefully. See [hotspot](hotspot.md) for AP preparation.

When you disable a declaration, Nacre withdraws management. Purge removes owned drop-ins. It keeps the current locale, timezone, hostname, console, firewall rules and hotspot properties.

## PowerPanel (CyberPower UPS)

`services.powerpanel` manages `/etc/pwrstatd.conf`, the `powerpanel` AUR package and `pwrstatd.service`. On power failure, its shutdown policy waits for the remaining-runtime threshold. It does not shut down immediately. Before you change the policy, inspect `powerfailShutdown`, `runtimeThreshold` and `lowbattShutdown`.

The deployment user joins `power`. Thus it can run `pwrstat -status` and `pwrstat -config` without root. A changed daemon configuration records pending work and restarts a running service.

## Changes and recovery

Adapters compare content, owner and mode before atomic replacement. They record intent under `/var/lib/nix-config/arch/` and clear it after success. Healthy reruns rewrite no identical files and restart no healthy services. logind changes wait until reboot. The adapter does not restart an active login session. fstrim keeps the native schedule with catch-up disabled. It refuses conflicting schedules.

Keep pending markers. Fix the reported cause, then run again. `nacre --verbose switch` shows native diagnostics.

For isolated validation:

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.system-settings-interface \
  .#checks.x86_64-linux.system-settings-tests \
  .#checks.x86_64-linux.core-tests \
  .#checks.x86_64-linux.arch-switch-tests \
  .#checks.x86_64-linux.system-firewall-integration
```
