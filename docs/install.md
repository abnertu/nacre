# Install

Nacre needs these items:

- An installed, booted Arch Linux `x86_64` system.
- Network access.
- A login account in `wheel` with a home under `/home/<name>`.

Disk partitioning and base-system installation stay outside Nacre.

## Steps

Read [the bootstrap](../scripts/bootstrap.sh). Then execute it:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
```

The script enables `[multilib]`, installs base packages, Nix and yay, and starts the Nix daemon. In a terminal, it offers to run `nacre install`. If group membership changed, log in again before you run the installation:

```bash
nix run github:abnertu/nacre#nacre -- install
```

Installation asks for user, hostname, role, time zone and locale. Then it does these steps:

1. Detects AMD graphics and initramfs images.
2. Writes the [machine template](../templates/machine/configuration.nix) and a flake that follows Nacre into `~/.config/nacre`.
3. Commits the generated files, so that Nix can see them.

To choose another checkout, use `--flake PATH`.

It shows a preview of the machine and asks before `nacre update`. For unattended installation, supply each value and `--yes`:

```bash
nix run github:abnertu/nacre#nacre -- install --user alice --hostname box \
  --role minimal --timezone Europe/Berlin --locale en_US.UTF-8 --yes
```

Without a terminal or `--yes`, installation stops after the plan. In an existing flake, installation protects uncommitted `configuration.nix` changes, unless you pass `--force`.

## Restore an existing machine

Before the bootstrap, clone the machine flake to `~/.config/nacre`. The bootstrap then tells you to run `nix run .#nacre -- plan`. Before deployment, restore the necessary external state with the [backup guide](backup.md).

## Afterwards

The activated home provides `nacre`. Add hardware, home modules and optional features as [configuration](configuration.md) describes. The [fixture](../checks/fixtures/configuration.nix) shows feature composition.

To adopt Nacre changes, in the machine checkout:

1. Run `nix flake update nacre`.
2. Review the lock diff and the output of `nacre plan`.
3. Run `nacre switch`.

Your configuration stays separate from the Nacre source.
