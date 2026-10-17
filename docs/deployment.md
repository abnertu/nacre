# Deployment and recovery

Run from this checkout as the deployment user on `x86_64-linux` Arch. Prerequisites:

- the account exists and is in `wheel`
- native Nix, `yay` and the required commands are installed
- `[multilib]` is enabled in `/etc/pacman.conf` when `lib32-*` packages are declared
- the running kernel has a matching module directory

Read [configuration](configuration.md), [system settings](system-settings.md) and the preparation guide of each enabled feature first.

## Bootstrap

On a fresh Arch install without Nix or just, run the bootstrap after cloning. It enables `[multilib]`, installs prerequisites, configures Nix and starts `nix-daemon.service`:

```bash
git clone https://github.com/gin31259461/nacre.git ~/.config/nix
cd ~/.config/nix
./scripts/bootstrap.sh
```

The bootstrap changes the host; read the script first.

## Commands

`nacre` is installed by the home generation. Before the first activation, run it from the checkout as `nix run .#nacre -- <command>`.

```bash
nacre plan                # read-only preview
nacre switch              # converge Arch, then activate the built home
nacre update              # also upgrade and converge declared pacman / AUR packages
nacre --verbose switch    # full diagnostics
nacre purge               # remove managed Arch state, skip home
```

- **status** shows the checkout revision, the last switch made through `nacre`, the active home generation and any pending markers.
- **generations** and **rollback [N]** list and reactivate earlier home generations. Rollback never touches Arch state: packages and `/etc` files stay as the last switch left them, and the next switch activates the current configuration again.
- **plan** lists missing and upgradable packages, every core file and runtime change, system and optional module preflight, and whether the Home Manager generation changes. Lines start with `=` (unchanged), `~` (changed), `+` (added) or `!` (conflict); conflicts exit non-zero. System settings show preflight only, not per-item detail.
- **Routine runs** install nothing. Missing packages exit with code 3; use `update`.
- **update** fully upgrades pacman and converges AUR. A kernel update may need a reboot.
- **purge** withdraws, in order:
  - AI: the Tailscale Serve route, the Caddy site, the `llama-swap` unit and config.
  - System settings: timesyncd, journald, logind and fstrim timer drop-ins.
  - Core: managed system units, kernel files, the LizardByte repository, the Personal Agent unit, the Nix configuration block and pending state.

  It keeps packages, accounts, Runner registrations, mutable data, prepared AI binaries and models, and the current locale, timezone, hostname, console, firewall rules and hotspot settings. The initramfs module block also stays, since withdrawing it needs a boot image rebuild. Files of disabled features are no longer managed and purge leaves them alone. Purge does not activate Home Manager.

A run preflights core state and optional modules, upgrades packages (with `update`), converges native files and services, then activates the home. The two stages share no rollback: if home activation fails, the Arch changes remain. Runners and [AI preparation](ai.md) are outside this flow.

An optional module is skipped as `not ready` only if it was never prepared; a skipped module's files and services are untouched. Invalid receipts, checksum drift, ownership conflicts, missing declared core hardware, native command failures and state changing after preflight all stop the run.

## Container test

`just container-test` deploys `checks/container/configuration.nix` (the workstation minus hardware and kernel features a rootless container cannot provide) into a systemd Arch container with podman, and checks that:

1. the checked-in bootstrap prepares the environment
2. a routine run with missing packages exits 3
3. `update` succeeds
4. a repeat run changes nothing
5. `plan` agrees nothing is left
6. pacman still works after purge
7. store paths are unmodified

Pacman and yay caches live in the `nix-config-container-pacman` and `nix-config-container-yay` volumes, so only the first run downloads everything. `--keep` leaves the container for inspection. CI runs the same test on deployment changes to `main`, weekly and on demand.

## Progress and diagnostics

Nix shows native build progress. During deployment a shared progress display tracks running, finished, skipped and failed tasks, and yields the terminal to native tool output. It falls back to plain logs with `verbose`, redirected stderr, `TERM=dumb`, any `NO_COLOR` or a non-empty `CI`. `verbose` reaches Nix, Home Manager and the privileged adapters. Adapter failures include the command, exit code, stdout, stderr and partial output before a timeout, with secrets redacted.


## Recovery

| Situation | Action |
| --- | --- |
| Exit 2 | Fix the command arguments |
| Exit 3 | Review the missing native packages, run `update` |
| Exit 75 | Wait for the lock, or boot the kernel matching the installed modules |
| Optional module skipped | Finish that module's preparation |
| Native command failed | Fix the reported cause and rerun the same command |

Managed writes record a pending marker in `/var/lib/nix-config/arch/` before changing anything and clear it after success. Keep the markers so a rerun can resume; deleting them hides unfinished work. A healthy rerun rewrites no identical files and restarts no healthy services. If Home Manager fails after Arch convergence, fix the home error and rerun. Purge is not a recovery shortcut.
