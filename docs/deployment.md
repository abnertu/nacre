# Deployment and recovery

Run as the deployment user on Arch Linux `x86_64`. The login account must exist and belong to `wheel`; native Nix, yay and required commands must be available. Declared `lib32-*` packages require `[multilib]`, and the running kernel needs its matching module directory.

`nacre` finds `~/.config/nacre` by default. Use `--flake PATH` for another checkout. Read the relevant [configuration](configuration.md), [system](system-settings.md) and feature preparation guides before deployment.

## Bootstrap

Follow [installation](install.md#steps) on a host without Nix. For a restore, clone the machine flake first and use `nix run .#nacre -- plan` before the first home activation.

## Commands

The home generation supplies `nacre` and bash/zsh completions. Before activation, use `nix run .#nacre -- <command>` from the machine checkout.

```bash
nacre plan                # preview without mutation
nacre switch              # converge Arch, then activate the built home
nacre update              # also upgrade declared pacman and AUR packages
nacre --verbose switch    # include native diagnostics
nacre purge               # withdraw managed Arch state without home activation
```

| Command | Behaviour |
| --- | --- |
| `status` | Show checkout revision, last recorded switch, active home and pending markers |
| `doctor` | Report revision drift, pending work, missing kernel modules, failed or unstarted units, uncaptured Noctalia preferences and backup files beside managed home files; exit 1 on findings |
| `changes [--since TIME]` | Read package changes from pacman's log since the last update started, or an explicit ISO date/time |
| `generations` | List previous home generations |
| `rollback [N]` | Reactivate a previous home; leave Arch packages and native files unchanged |
| `plan` | Compare packages, native state, module readiness and the home generation; conflicts fail |

Plan prefixes are `=` unchanged, `~` changed, `+` added and `!` conflict. System settings expose preflight results rather than individual changes. The next switch after a rollback activates the current declaration again.

Routine runs install nothing and exit 3 when packages are missing. `update` fully upgrades pacman and converges AUR; a kernel upgrade may require a reboot. Its final doctor report does not change the update's exit status.

Pass `--override-input INPUT REF` to apply an input override to every Nix evaluation. For example, `nacre --override-input nacre path:$HOME/codebase/nacre plan` previews local Nacre changes. Publish the change and adopt it with a lock update before relying on it routinely.

## Failure and purge boundaries

Deployment preflights core state and optional modules, converges packages only during update, converges native state, then activates the embedded home. If home activation fails, Arch changes remain.

A module may skip as `not ready` only before its preparation has ever completed; skipped modules keep their files and services untouched. Invalid receipts, checksum drift, ownership conflicts, missing core hardware, failed native commands and readiness changing after preflight stop the run.

Purge withdraws AI's Tailscale route, Caddy site and llama-swap configuration; system-setting drop-ins; managed core units, kernel files, repository configuration, extension-owned units, Nix settings and pending state. It keeps packages, accounts, registrations, mutable data, prepared AI artifacts and the current locale, timezone, hostname, console, firewall and hotspot settings. The initramfs module block remains because removing it needs a boot-image rebuild. Disabled features are no longer managed and are left alone. Home Manager does not activate.

## Container test

`just container-test` runs the checked-in bootstrap and [container configuration](../checks/container/configuration.nix) in a disposable systemd Arch container. It verifies missing-package rejection, update, quiet repeat convergence, an unchanged plan, purge, installation of a new minimal machine and Nix store integrity. Hardware and kernel features unavailable to the container are disabled.

Pacman and yay caches persist in `nacre-container-pacman` and `nacre-container-yay` volumes. `--keep` retains the test container. The Arch deployment lifecycle workflow runs on deployment changes to `main`, weekly and on request.

## Progress and diagnostics

Nix reports build progress. Deployment tracks running, finished, skipped and failed tasks, yielding to native tool output when needed. Verbose mode, redirected stderr, `TERM=dumb`, any `NO_COLOR` or non-empty `CI` selects plain logs. Verbose mode reaches Nix, Home Manager and privileged adapters.

Adapter failures report the command, exit code, stdout, stderr and partial timeout output with secrets redacted.

## Recovery

| Result | Next step |
| --- | --- |
| Exit 2 | Correct the arguments |
| Exit 3 | Review missing packages and run `update` |
| Exit 75 | Wait for the lock or boot a kernel matching installed modules |
| Module skipped | Complete its preparation |
| Native or home failure | Fix the reported cause and rerun |

Managed mutations first write a pending marker under `/var/lib/nix-config/arch/` and clear it after success. Keep markers during recovery. Healthy reruns preserve identical files and healthy services; purge is not a recovery shortcut.

## Migrating older machines

### From `~/.config/nix` (before 0.1.0)

Deploy 0.1.x before moving the checkout so `/etc/nix/nix.conf` receives the managed flakes settings:

```bash
nacre switch
grep -A6 'BEGIN nix-config settings' /etc/nix/nix.conf
mv ~/.config/nix ~/.config/nacre
```

Version 0.2.0 removes the transitional user `nix.conf`. If already updated without deploying 0.1.x, pass `--extra-experimental-features 'nix-command flakes'` to the first `nix run .#nacre`. Nacre still discovers either checkout location.

### Out of a Nacre clone (before 0.5.0)

Move personal machine files out before updating a clone that contains them:

```bash
mkdir ~/machine && cd ~/machine && git init
cp ~/.config/nacre/templates/machine/flake.nix .
cp -r ~/.config/nacre/{configuration.nix,hosts,homes} .
git add -A
nacre --flake ~/machine plan
```

Restore needed dotfiles with `git show v0.4.0:files/home/...`, project them through [home modules](configuration.md#users-and-homes), and declare applications removed from the baseline in `packages.extra`. Replace the old checkout with the machine flake, then switch.
