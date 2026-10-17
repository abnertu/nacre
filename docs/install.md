# Install

Nacre layers onto an existing Arch Linux install; it does not partition disks or install the base system.

## Before you start

- Arch Linux `x86_64`, booted into the installed system
- your login account, in `wheel`, with its home at `/home/<name>`
- a network connection

## Steps

```bash
git clone https://github.com/gin31259461/nacre ~/.config/nix
cd ~/.config/nix
./scripts/bootstrap.sh              # multilib, base packages, Nix and its daemon
nix run .#nacre -- install
```

`install` asks for the user, hostname, role, time zone and locale, offering this machine's current values. It detects AMD graphics and the initramfs images under `/boot`, writes `configuration.nix` from [the template](../templates/configuration.nix), shows `nacre plan`, and runs `nacre update` once you confirm.

For an unattended install, pass every value and `--yes`:

```bash
nix run .#nacre -- install --user alice --hostname box --role minimal \
  --timezone Europe/Berlin --locale en_US.UTF-8 --yes
```

Without `--yes` and without a terminal, it stops after the plan. It refuses to replace a `configuration.nix` with uncommitted changes unless you pass `--force`; committed versions stay in Git.

## Afterwards

The home generation installs `nacre`, so later runs are `nacre plan` and `nacre switch`. The generated file is a starting point: add hardware, features and home settings as described in [configuration](configuration.md), and enable opt-in features such as the [hotspot](hotspot.md), [local AI](ai.md), [Runners](runners.md) or the [Personal Agent](personal-agent.md) when you need them.
