# Deploy and recover the Arch workstation

Run from this checkout as the selected existing login user on `x86_64-linux` Arch. The account must be in `wheel`; native Nix, `yay` and the required commands must be available. Declared `lib32-*` packages need the `[multilib]` repository enabled in `/etc/pacman.conf`. The running kernel needs its installed module directory. Review [configuration](configuration.md), [system ownership](system-settings.md) and any enabled feature's preparation guide before activation.

## Bootstrap

On a freshly installed Arch machine lacking Nix or Just, clone this repository to the user's configuration checkout and run the checked-in bootstrap script there. It enables `[multilib]`, installs native prerequisites, configures Nix and starts `nix-daemon.service`:

```bash
git clone https://github.com/gin31259461/nix-config.git ~/.config/nix
cd ~/.config/nix
./scripts/bootstrap.sh
```

Bootstrap changes the live machine. Inspect the script and local package state first. It is separate from source validation.

## Container smoke test

`just container-test` deploys `checks/container/configuration.nix` (the operator configuration minus hardware and kernel features a rootless container lacks) into a systemd Arch container with podman. It bootstraps with the checked-in script, then expects exit 3 before packages, a successful `update`, a repeat run with no changes, a purge that keeps pacman usable, and unmodified store paths. Pacman and yay caches persist in the `nix-config-container-pacman` and `nix-config-container-yay` volumes; the first run downloads the full package set. `--keep` leaves the container running for inspection. CI runs the same test when deployment sources change on `main`, weekly and on request (`.github/workflows/container-test.yml`), restoring the package caches between runs.

## Source checks and activation

```bash
just check-fast                 # Source formatting, types and selected interfaces.
just check                      # All flake checks, including isolated tests.
just build                      # Build the deployment without activation.
just arch-workstation           # Converge Arch, then activate the fixed home.
just arch-workstation update    # Upgrade/converge declared pacman and AUR packages too.
just arch-workstation verbose   # Propagate verbose diagnostics throughout the run.
just arch-workstation purge     # Remove managed Arch deployment state; skip home.
```

A routine run does not install missing native packages and exits 3 if they are absent. `update` performs a full pacman upgrade and declared AUR convergence. A kernel update may require a reboot before later convergence. `purge` disables managed system units and removes the currently declared core files, the LizardByte repository entry, the Personal Agent unit, pending state and the Nix configuration block while preserving installed packages, accounts, Runner registrations and mutable application data. Files of capabilities already disabled are no longer managed, so purge leaves them. It does not withdraw system-settings, AI or initramfs changes, and it does not activate Home Manager.

`just arch-workstation` first builds a deployment artifact containing one exact Home Manager activation package. Runtime preflights core system state and optional readiness, optionally updates packages, converges native files and services, then activates that built home. Arch changes remain applied if home activation fails; the stages have no shared rollback transaction. Runner reconciliation and registration are outside this sequence. [AI preparation](ai.md) is also separate.

An optional adapter may report `not ready` only when it has never completed required preparation. Its highlighted skip leaves its files and services untouched. Invalid receipts, checksum drift, ownership conflicts, missing declared core hardware, native command failures and readiness changes after preflight stop deployment.

## Progress and diagnostics

Nix shows its native build progress. After launch, shared task progress reports active, completed, skipped and failed tasks while yielding the terminal to native tools. `verbose`, redirected stderr, `TERM=dumb`, `NO_COLOR` (even empty) or nonempty `CI` select plain logs. `verbose` reaches Nix, Home Manager and privileged adapters. Adapter failures include command, exit status, stdout, stderr and partial timeout output with secrets redacted.

```bash
NO_COLOR=1 just build
just arch-workstation update verbose
```

For direct invocation, Nix flags precede the target and adapter flags follow `--`:

```bash
nix run --show-trace --print-build-logs --verbose .#arch-workstation -- --verbose
```

## Recover an interrupted run

| Signal | Response |
| --- | --- |
| Exit 2 | Correct the command arguments. |
| Exit 3 | Review missing native packages, then run `update` if intended. |
| Exit 75 | Wait for the lock or boot a kernel with matching installed modules. |
| Optional skip | Complete that module's explicit preparation. |
| Native failure | Correct the reported cause and rerun the same command. |

Managed writes record pending actions under `/var/lib/nix-config/arch/` before mutation and clear them only after success. Keep those markers for retry; do not delete them to mask unfinished work. Healthy repeat runs avoid rewriting identical files and restarting healthy services. If Home Manager fails after Arch convergence, correct the home error and rerun deployment. Do not treat `purge` as a recovery shortcut.
