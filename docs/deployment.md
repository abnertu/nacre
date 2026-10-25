# Deployment and recovery

Run as the deployment user on Arch Linux `x86_64`. The login account must exist and belong to `wheel`. Native Nix, yay and the necessary commands must be available. Declared `lib32-*` packages need `[multilib]`. The running kernel needs its matching module directory.

`nacre` finds `~/.config/nacre` by default. Use `--flake PATH` for another checkout. Before deployment, read the relevant [configuration](configuration.md), [system](system-settings.md) and feature preparation guides.

## Bootstrap

On a host without Nix, follow [installation](install.md#steps). For a restore, clone the machine flake first. Before the first home activation, use `nix run .#nacre -- plan`.

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
| `doctor` | Report revision drift, pending work and missing kernel modules. Report failed or unstarted units, uncaptured Noctalia preferences and backup files beside managed home files. Exit 1 on findings. |
| `changes [--since TIME]` | Read package changes from the pacman log since the start of the last update, or since an explicit ISO date/time |
| `generations` | List previous home generations |
| `rollback [N]` | Activate a previous home again. Arch packages and native files do not change. |
| `plan` | Compare packages, native state, module readiness and the home generation. Conflicts fail. |

Plan prefixes are `=` unchanged, `~` changed, `+` added and `!` conflict. System settings show preflight results, not individual changes. The next switch after a rollback activates the current declaration again.

Routine runs install nothing. They exit 3 when packages are missing. `update` fully upgrades pacman and converges AUR. A kernel upgrade can need a reboot. The final doctor report does not change the exit status of the update.

To apply an input override to each Nix evaluation, pass `--override-input INPUT REF`. For example, `nacre --override-input nacre path:$HOME/codebase/nacre plan` shows a preview of local Nacre changes. Before routine use, publish the change and adopt it with a lock update.

## Failure and purge boundaries

Deployment does these steps:

1. Preflights core state and optional modules.
2. Converges packages, only during update.
3. Converges native state.
4. Activates the embedded home.

If home activation fails, the Arch changes stay.

A module can skip as `not ready` only before its preparation has ever completed. Nacre does not touch the files and services of a skipped module. Each of these conditions stops the run:

- Invalid receipts.
- Checksum drift.
- Ownership conflicts.
- Missing core hardware.
- Failed native commands.
- A readiness change after preflight.

Purge withdraws these items:

- The AI Tailscale route, Caddy site and llama-swap configuration.
- System-setting drop-ins.
- Managed core units, kernel files and repository configuration.
- Extension-owned units, Nix settings and pending state.

Purge keeps these items:

- Packages, accounts, registrations, mutable data and prepared AI artifacts.
- The current locale, timezone, hostname, console, firewall and hotspot settings.
- The initramfs module block, because its removal needs a boot-image rebuild.

Nacre no longer manages disabled features and does not touch them. Home Manager does not activate.

## Container test

`just container-test` runs the checked-in bootstrap and [container configuration](../checks/container/configuration.nix) in a disposable systemd Arch container. It verifies these behaviours:

- Missing-package rejection and update.
- Quiet repeat convergence and an unchanged plan.
- Purge.
- Installation of a new minimal machine.
- Nix store integrity.

The test disables hardware and kernel features that the container cannot use.

Pacman and yay caches persist in the `nacre-container-pacman` and `nacre-container-yay` volumes. `--keep` keeps the test container. The Arch deployment lifecycle workflow runs on deployment changes to `main`, each week and on request.

## Progress and diagnostics

Nix reports build progress. Deployment tracks running, finished, skipped and failed tasks. When necessary, it gives way to native tool output. Each of these selects plain logs: verbose mode, redirected stderr, `TERM=dumb`, a `NO_COLOR` value or a non-empty `CI`. Verbose mode reaches Nix, Home Manager and privileged adapters.

Adapter failures report the command, exit code, stdout, stderr and partial timeout output. Secrets are redacted.

## Recovery

| Result | Next step |
| --- | --- |
| Exit 2 | Correct the arguments |
| Exit 3 | Review missing packages and run `update` |
| Exit 75 | Wait for the lock or boot a kernel matching installed modules |
| Module skipped | Complete its preparation |
| Native or home failure | Fix the reported cause, then run again |

Managed mutations first write a pending marker under `/var/lib/nix-config/arch/`. They clear it after success. Keep markers during recovery. Healthy reruns keep identical files and healthy services. Purge is not a recovery shortcut.

## Migrating older machines

### From `~/.config/nix` (before 0.1.0)

Deploy 0.1.x before you move the checkout. Then `/etc/nix/nix.conf` gets the managed flakes settings:

```bash
nacre switch
grep -A6 'BEGIN nix-config settings' /etc/nix/nix.conf
mv ~/.config/nix ~/.config/nacre
```

Version 0.2.0 removes the transitional user `nix.conf`. If you updated without a deployment of 0.1.x, pass `--extra-experimental-features 'nix-command flakes'` to the first `nix run .#nacre`. Nacre still discovers either checkout location.

### Out of a Nacre clone (before 0.5.0)

Before you update a clone that contains personal machine files, move them out:

```bash
mkdir ~/machine && cd ~/machine && git init
cp ~/.config/nacre/templates/machine/flake.nix .
cp -r ~/.config/nacre/{configuration.nix,hosts,homes} .
git add -A
nacre --flake ~/machine plan
```

1. Restore the necessary dotfiles with `git show v0.4.0:files/home/...`.
2. Project them through [home modules](configuration.md#users-and-homes).
3. Declare applications that the baseline removed in `packages.extra`.
4. Replace the old checkout with the machine flake.
5. Run `nacre switch`.
