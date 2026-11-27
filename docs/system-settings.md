# System settings

The system adapter owns locale, timezone, console, hostname, firewall, hotspot and selected native service settings. Core adapters own the remaining native files, units, group memberships, system accounts and kernel parameters. Their Nix-generated manifests define both convergence and purge. Home Manager does not own these `/etc` files.

| Options | Native resources |
| --- | --- |
| `i18n`, `time`, `console` | Locale, timezone, keymap and font |
| `networking.hostname`, `networking.firewall`, `networking.hotspot` | Hostname, UFW and an existing NetworkManager AP |
| `services.timesyncd`, `services.journald`, `services.logind`, `services.fstrim`, `services.powerpanel` | Native settings, service state and UPS configuration |

Preflight checks files, ownership, commands and units before mutations. Missing interfaces or resources, conflicting providers and failed queries stop the core stage. Before the first adoption, inspect current ownership from a local session that permits recovery. Examine UFW, networking, time sync, storage discard and console settings carefully. See [hotspot](hotspot.md) to create the AP connection with `nacre hotspot prepare`.

When a setting goes away, Nacre returns it to its state before Nacre. The system receipt `/var/lib/nix-config/arch/receipts/system.json` records each change:

- A drop-in goes away. systemd reloads and the service restarts. logind changes apply after the next boot.
- The locale, console, time zone and hostname get their values before Nacre back. A file that Nacre created goes away.
- The `locale.gen` block goes away, and `locale-gen` runs.
- A UFW rule that Nacre added goes away. A rule whose port carries an established TCP connection stays, and the deployment stops.
- A UFW withdrawal that disables UFW, lowers its logging or allows new application profiles stops the deployment. Run the named command from a local console if you want it.
- The hotspot connection gets its properties back. An AP that Nacre brought up goes down.

A value that changed since Nacre set it stops the deployment. Restore it, or run `nacre forget <kind>:<name>` to leave it unmanaged. The kinds are `dropin`, `locale`, `console`, `timezone`, `hostname`, `ufw`, `firewall` and `hotspot`.

Purge withdraws all settings the same way. It keeps UFW and its rules.

## PowerPanel (CyberPower UPS)

`services.powerpanel` manages `/etc/pwrstatd.conf`, the `powerpanel` AUR package and `pwrstatd.service`. On power failure, its shutdown policy waits for the remaining-runtime threshold. It does not shut down immediately. Before you change the policy, inspect `powerfailShutdown`, `runtimeThreshold` and `lowbattShutdown`.

The deployment user joins `power`. Thus it can run `pwrstat -status` and `pwrstat -config` without root. A changed daemon configuration restarts a running service once, through `restartTriggers`.

## Changes and recovery

Adapters compare content, owner and mode before atomic replacement. They record intent under `/var/lib/nix-config/arch/` and clear it after success. Healthy reruns keep identical files and leave healthy services running. logind changes wait until reboot. The adapter does not restart an active login session. fstrim keeps the native schedule with catch-up disabled. It refuses conflicting schedules.

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
