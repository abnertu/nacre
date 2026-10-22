# Install

Nacre requires an installed, booted Arch Linux `x86_64` system, network access and a login account in `wheel` with a home under `/home/<name>`. Disk partitioning and base-system installation remain outside Nacre.

## Steps

Read [the bootstrap](../scripts/bootstrap.sh), then execute it:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
```

The script enables `[multilib]`, installs base packages, Nix and yay, and starts the Nix daemon. In a terminal it offers to run `nacre install`. If group membership changed, log in again before running installation:

```bash
nix run github:abnertu/nacre#nacre -- install
```

Installation asks for user, hostname, role, time zone and locale. It detects AMD graphics and initramfs images, writes the [machine template](../templates/machine/configuration.nix) and a flake following Nacre into `~/.config/nacre`, and commits the generated files so Nix can see them. Use `--flake PATH` to choose another checkout.

It previews the machine and asks before `nacre update`. For unattended installation, supply every value and `--yes`:

```bash
nix run github:abnertu/nacre#nacre -- install --user alice --hostname box \
  --role minimal --timezone Europe/Berlin --locale en_US.UTF-8 --yes
```

Without a terminal or `--yes`, installation stops after the plan. In an existing flake, uncommitted `configuration.nix` changes are protected unless `--force` is passed.

## Restore an existing machine

Clone its machine flake to `~/.config/nacre` before bootstrapping. The bootstrap then directs you to `nix run .#nacre -- plan`; restore required external state using the [backup guide](backup.md) before deployment.

## Afterwards

The activated home provides `nacre`. Add hardware, home modules and optional features using [configuration](configuration.md); the [fixture](../checks/fixtures/configuration.nix) demonstrates feature composition.

To adopt Nacre changes, run `nix flake update nacre` in the machine checkout, review the lock diff and `nacre plan`, then switch. Your configuration remains separate from Nacre's source.
