# Install

Nacre layers onto an existing Arch Linux install; it does not partition disks or install the base system.

## Before you start

- Arch Linux `x86_64`, booted into the installed system
- your login account, in `wheel`, with its home at `/home/<name>`
- a network connection

## Steps

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
```

The [bootstrap](../scripts/bootstrap.sh) enables `[multilib]`, installs the base packages, Nix and yay, and starts the Nix daemon; it changes the host, so read it first (`curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh | less`). On a terminal it then offers to run `nacre install`. If it added you to `wheel`, log in again and run install yourself:

```bash
nix run github:abnertu/nacre#nacre -- install
```

`install` asks for the user, hostname, role, time zone and locale, offering this machine's current values. It detects AMD graphics and the initramfs images under `/boot`, then creates your machine's flake in `~/.config/nacre`:

- `flake.nix` follows Nacre: `nacre.lib.mkFlake { modules = [ ./configuration.nix ]; }`
- `configuration.nix` is written from [the template](../templates/machine/configuration.nix)
- both are committed to a new Git repository, since Nix only reads tracked files

It then shows `nacre plan` and runs `nacre update` once you confirm. Pass `--flake PATH` for another location.

For an unattended install, pass every value and `--yes`:

```bash
nix run github:abnertu/nacre#nacre -- install --user alice --hostname box \
  --role minimal --timezone Europe/Berlin --locale en_US.UTF-8 --yes
```

Without `--yes` and without a terminal, it stops after the plan. In an existing flake, it refuses to replace a `configuration.nix` with uncommitted changes unless you pass `--force`.

## Afterwards

The home generation installs `nacre`, so later runs are `nacre plan` and `nacre switch`. Upgrade Nacre itself with `nix flake update nacre` in `~/.config/nacre`, review `nacre plan`, then switch; your configuration never merges with Nacre's code.

The generated file is a starting point: add hardware, features and home settings as described in [configuration](configuration.md), and enable opt-in features such as the [hotspot](hotspot.md) or [local AI](ai.md) when you need them. The [fixture machine](../checks/fixtures/configuration.nix) enables every feature and serves as a full example.
