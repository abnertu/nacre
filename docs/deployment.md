# Deployment and recovery

Run from the machine flake's checkout (`~/.config/nacre`, which `nacre` finds by default) as the deployment user on `x86_64-linux` Arch. Prerequisites:

- the account exists and is in `wheel`
- native Nix, `yay` and the required commands are installed
- `[multilib]` is enabled in `/etc/pacman.conf` when `lib32-*` packages are declared
- the running kernel has a matching module directory

Read [configuration](configuration.md), [system settings](system-settings.md) and the preparation guide of each enabled feature first.

## Bootstrap

On a host without Nix, run the [bootstrap](install.md#steps) first. To restore an existing machine, clone its flake to `~/.config/nacre` before running it; the bootstrap then points you at `nix run .#nacre -- plan`.

## Commands

`nacre` is installed by the home generation, with bash and zsh completions; a new shell picks them up. Before the first activation, run it from the checkout as `nix run .#nacre -- <command>`.

```bash
nacre plan                # read-only preview
nacre switch              # converge Arch, then activate the built home
nacre update              # also upgrade and converge declared pacman / AUR packages
nacre --verbose switch    # full diagnostics
nacre purge               # remove managed Arch state, skip home
```

`--override-input INPUT REF` passes a flake input override to every Nix evaluation, so a machine flake can deploy an unpublished Nacre checkout: `nacre --override-input nacre path:$HOME/codebase/nacre switch`. Commit and release the change, then `nix flake update nacre` to adopt it.

- **status** shows the checkout revision, the last switch made through `nacre`, the active home generation and any pending markers.
- **doctor** reports what needs attention and changes nothing: a checkout ahead of the last switch, pending markers, a running kernel without installed modules, failed units, home units enabled under an active target that never started, Noctalia GUI changes not yet captured, and `.bak`, `.backup`, `.orig` or `.old` files beside managed home files. It exits 1 when anything is reported, and `update` runs it at the end without changing the update's exit status.
- **changes [--since TIME]** lists the packages upgraded, downgraded, installed, reinstalled or removed since the last `nacre update` started, read from `/var/log/pacman.log`. Start here when something behaves differently after an update. `--since` takes an ISO date or time.
- **generations** and **rollback [N]** list and reactivate earlier home generations. Rollback never touches Arch state: packages and `/etc` files stay as the last switch left them, and the next switch activates the current configuration again.
- **plan** lists missing and upgradable packages, every core file and runtime change, system and optional module preflight, and whether the Home Manager generation changes. Lines start with `=` (unchanged), `~` (changed), `+` (added) or `!` (conflict); conflicts exit non-zero. System settings show preflight only, not per-item detail.
- **Routine runs** install nothing. Missing packages exit with code 3; use `update`.
- **update** fully upgrades pacman and converges AUR. A kernel update may need a reboot.
- **purge** withdraws, in order:
  - AI: the Tailscale Serve route, the Caddy site, the `llama-swap` unit and config.
  - System settings: timesyncd, journald, logind and fstrim timer drop-ins.
  - Core: managed system units, kernel files, the LizardByte repository, the units of [extensions](configuration.md#machine-extensions), the Nix configuration block and pending state.

  It keeps packages, accounts, registrations, mutable data, prepared AI binaries and models, and the current locale, timezone, hostname, console, firewall rules and hotspot settings. The initramfs module block also stays, since withdrawing it needs a boot image rebuild. Files of disabled features are no longer managed and purge leaves them alone. Purge does not activate Home Manager.

A run preflights core state and optional modules, upgrades packages (with `update`), converges native files and services, then activates the home. The two stages share no rollback: if home activation fails, the Arch changes remain. [AI preparation](ai.md) is outside this flow.

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

Pacman and yay caches live in the `nacre-container-pacman` and `nacre-container-yay` volumes, so only the first run downloads everything. `--keep` leaves the container for inspection. CI runs the same test on deployment changes to `main`, weekly and on demand.

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

## Migrating older machines

### From `~/.config/nix` (before 0.1.0)

Checkouts older than 0.1.0 live at `~/.config/nix`, where Nix also reads user settings; 0.1.x shipped a transitional `nix.conf` there to enable flakes, and 0.2.0 removes it. Deploy 0.1.x first, so the `nix.settings` block in `/etc/nix/nix.conf` enables flakes, then move:

```bash
nacre switch
grep -A6 'BEGIN nix-config settings' /etc/nix/nix.conf   # experimental-features is there
mv ~/.config/nix ~/.config/nacre
```

A checkout updated to 0.2.0 before that deployment needs `--extra-experimental-features 'nix-command flakes'` on its first `nix run .#nacre`. `nacre` still finds a checkout at either location.

### Out of a Nacre clone (before 0.5.0)

Before 0.5.0 a machine could live inside a clone of Nacre: its `configuration.nix`, `hosts/` and `homes/`, plus the dotfiles the `workstation` profile projected from `files/home` (kitty, ghostty, cava, btop, fastfetch and others). 0.5.0 removes all of them. Move them into a machine flake:

```bash
mkdir ~/machine && cd ~/machine && git init
cp ~/.config/nacre/templates/machine/flake.nix .
cp -r ~/.config/nacre/{configuration.nix,hosts,homes} .   # before updating that clone
git add -A
nacre --flake ~/machine plan                               # only a new home generation
```

Restore the dotfiles you used from `git show v0.4.0:files/home/...` into the flake and project them from a home module ([configuration](configuration.md#users-and-homes)); applications that left the workstation baseline go into `packages.extra`. Then replace `~/.config/nacre` with the new flake and run `nacre switch`.
