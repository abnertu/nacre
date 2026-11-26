# Deployment and recovery

Run as the deployment user on Arch Linux `x86_64`. The login account must exist and belong to `wheel`. Nix, yay and the required native commands must be available. Declared `lib32-*` packages need `[multilib]`. The running kernel needs its matching module directory.

`nacre` finds `~/.config/nacre` by default. Use `--dir PATH` or `NACRE_DIR` for another checkout. Before deployment, read the relevant [configuration](configuration.md), [system](system-settings.md) and feature preparation guides.

## Bootstrap

On a host without Nix, follow [installation](install.md#steps). For a restore, set `NACRE_REPO` as [Restore an existing machine](install.md#restore-an-existing-machine) shows. Before the first home activation, use `nix run .#nacre -- plan` in the checkout.

## Commands

The home generation supplies `nacre` and bash/zsh completions. Before activation, use `nix run .#nacre -- <command>` from the machine checkout.

```bash
nacre plan                # preview without mutation
nacre switch              # converge Arch, then activate the built home
nacre upgrade system      # also upgrade declared pacman and AUR packages
nacre upgrade self        # adopt the newest Nacre, plan, then switch
nacre --verbose switch    # include native diagnostics
nacre forget file:NAME    # leave one drifted record unmanaged
nacre purge               # withdraw managed Arch state without home activation
```

| Command | Behavior |
| --- | --- |
| `build` | Build without activation, then print the deployment artifact path. |
| `status` | Show checkout revision, last recorded switch, active home and pending markers |
| `checkhealth` | Report revision drift, pending work and missing kernel modules. Report failed or unstarted units, uncaptured Noctalia preferences and backup files beside managed home files. Exit 1 on findings. |
| `changes [--since TIME]` | Read package changes from the pacman log since the start of the last update, or since an explicit ISO date/time |
| `generations` | List previous home generations |
| `rollback [N]` | Activate a previous home again. Arch packages and native files do not change. |
| `plan` | Compare packages, native state, module readiness and the home generation. Conflicts fail. |

Plan prefixes are `=` unchanged, `~` changed, `+` added and `!` conflict. System settings show preflight results, not individual changes. The next switch after a rollback activates the current declaration again.

Routine runs install nothing. They exit 3 when packages are missing. `upgrade system` fully upgrades pacman and converges AUR. A kernel upgrade can need a reboot. The final `checkhealth` report does not change the exit status of the upgrade.

`upgrade self` changes only the `nacre` input of the machine flake. A release pin (`github:abnertu/nacre/vX.Y.Z`) moves to the newest tag. A branch pin keeps its URL and refreshes its lock entry. A pin newer than the newest release is refused. A failed lookup or lock update restores `flake.nix` and `flake.lock`. Without `--yes` and without a terminal, it stops after the plan.

To apply an input override to each Nix evaluation, pass `--override-input INPUT REF`. For example, `nacre --override-input nacre path:$HOME/codebase/nacre plan` shows a preview of local Nacre changes. Before routine use, publish the change and adopt it with a lock update.

## Failure and purge boundaries

Deployment does these steps:

1. Preflights core state and optional modules.
2. Converges packages, only during update.
3. Converges native state.
4. Activates the embedded home.

If home activation fails, the Arch changes stay.

Enabled [GitLab Runner](gitlab-runner.md) instances reconcile after core convergence and before Home Manager activation.
Their preflight does not require registration. Controller errors stop deployment; they never become preparation skips.

A module can skip as `not ready` only before its preparation has ever completed. Nacre does not touch the files and services of a skipped module. Each of these conditions stops the run:

- Invalid receipts.
- Checksum drift.
- A withdrawn file that changed since Nacre wrote it.
- An existing file that differs from a declaration without `adopt`.
- A host deployed by Nacre 0.11 or older.
- Ownership conflicts.
- Missing core hardware.
- Failed native commands.
- A readiness change after preflight.

`nacre purge` uninstalls Nacre. The core and system adapters check every record for drift before any extension hook or retirement runs. Then it withdraws everything that a deployment would withdraw when all declarations go away:

- Policy retired by explicitly opted-in extension adapters.
- The AI Tailscale route, Caddy site and llama-swap configuration.
- Units. Network units such as NetworkManager and tailscaled stop last.
- Recorded `/etc` files. Adopted files get their originals back.
- System-setting drop-ins. The locale, console, time zone, hostname and hotspot get their values before Nacre back.
- Groups, file capabilities, sysctl values and kernel modules that Nacre set. `wheel` stays.
- The repository, the `nix.conf` block and the initramfs block. The boot images are rebuilt.
- The deployment state under `/var/lib/nix-config/arch`.

Purge keeps these items:

- Packages, accounts, registrations, mutable data and prepared AI artifacts.
- UFW, `ufw.service` and the UFW rules.

A second purge changes nothing. Home Manager does not activate.

Extension purge hooks run in extension-name order before built-in retirement. A hook failure stops purge before shared pending state is removed. Purge does not skip opted-in hooks because preparation is incomplete.

## Container test

`just container-test` runs the checked-in install script and [container configuration](../checks/container/configuration.nix) in a disposable systemd Arch container. It verifies these behaviors:

- Missing-package rejection and update.
- Quiet repeat convergence and an unchanged plan.
- A withdrawal generation that removes declared files, a unit, a drop-in and a sysctl value.
- Purge, and a second purge that changes nothing.
- Installation of a new minimal machine.
- Nix store integrity.

The test disables hardware and kernel features that the container cannot use.

Pacman and yay caches persist in the `nacre-container-pacman` and `nacre-container-yay` volumes. `--keep` keeps the test container. The Test Deployment Lifecycle workflow runs on deployment changes to `main`, each week and on request.

## Native Runner test

The [Runner VM fixture](../modules/gitlab-runner/tests/native-vm.nix) exercises real accounts, subordinate allocations, user services, sockets and rootless containers.
It uses local HTTPS health and a deterministic image containing the locked Nixpkgs Runner binary.
Its TLS private key exists only inside the disposable guest.

The fixture simulates Arch package inventories, unrelated adapters and home activation inside a NixOS VM.
It does not verify Arch package installation, official image contents, registration or GitLab jobs.
`just check` requires this native lifecycle test with the published controller from the lock file.
The Validate workflow runs the same check set and requires KVM access.
Missing KVM access fails validation.

## Progress and diagnostics

Version, status, build results and CLI errors use colors on terminals.
Redirected output, `NO_COLOR`, `TERM=dumb` and non-empty `CI` disable these colors.
A successful cached build still prints its deployment artifact.

Nix reports build progress. Deployment tracks running, finished, skipped and failed tasks. Deployment displays native tool output when necessary. Each of these selects plain logs: verbose mode, redirected stderr, `TERM=dumb`, a `NO_COLOR` value or a non-empty `CI`. Verbose mode reaches Nix, Home Manager and privileged adapters.

Adapter failures report the command, exit code, stdout, stderr and partial timeout output. Secrets are redacted.

## Recovery

| Result | Next step |
| --- | --- |
| Exit 2 | Correct the arguments |
| Exit 3 | Review missing packages and run `upgrade system` |
| Exit 75 | Wait for the lock or boot a kernel matching installed modules |
| Module skipped | Complete its preparation |
| Native or home failure | Fix the reported cause, then run again |

Managed mutations first write a pending marker under `/var/lib/nix-config/arch/`. They clear it after success. Keep markers during recovery. Healthy reruns keep identical files and healthy services. Purge is not a recovery shortcut.

The receipt at `/var/lib/nix-config/arch/receipts/core.json` records each file that Nacre writes. Saved originals stay under `/var/lib/nix-config/arch/adopted/`, readable only by root. Never edit or copy them by hand. An interrupted run completes its record on the next run. A corrupt receipt stops the deployment. Without a receipt, an existing file identical to its declaration counts as Nacre's own, and withdrawal removes it.

| Stop | Next step |
| --- | --- |
| `set adopt = true` | Review the existing file, then set `adopt` on its entry or remove the entry |
| `changed since Nacre wrote it` | Restore or delete the file, or run `nacre forget file:<name>` |
| `deployed by an older Nacre` | Follow [From 0.11.x](#from-011x) |

`nacre forget` drops one record and its saved original. The file stays as it is.

## Migrating older machines

### From 0.11.x

This version keeps no compatibility with the state of older versions. Do these steps on the machine:

1. With the installed 0.11 Nacre, run `nacre purge`.
2. Run `nacre upgrade self`. It adopts this version, shows the plan, then switches.

Purge keeps packages, accounts, data and the current system settings. The new deployment adopts the existing files and saves them as originals.

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
nacre --dir ~/machine plan
```

1. Restore the necessary dotfiles with `git show v0.4.0:files/home/...`.
2. Project them through [home modules](configuration.md#users-and-homes).
3. Declare applications that the baseline removed in `packages.extra`.
4. Replace the old checkout with the machine flake.
5. Run `nacre switch`.
