# Install

Nacre needs these items:

- An installed, booted Arch Linux `x86_64` system.
- Network access.
- A login account in `wheel` with a home under `/home/<name>`.

Disk partitioning and base-system installation stay outside Nacre.

## Steps

Read [the install script](../scripts/install.sh). Then run it:

```bash
bash <(curl -fsSL https://github.com/abnertu/nacre/releases/latest/download/install.sh)
```

When a prerequisite is missing, the script enables `[multilib]` and installs base packages, Nix and yay with `pacman -Syu`. It starts the Nix daemon. Then it runs the newest release of `nacre` in the checkout:

| Checkout | Command |
| --- | --- |
| `NACRE_DIR`, else `~/.config/nacre`, else `~/.config/nix`, with a `flake.nix` | `nacre upgrade self` |
| None, `NACRE_REPO` set | `nacre install --repo "$NACRE_REPO"` |
| None | `nacre install` |

`~/.config` stands for `$XDG_CONFIG_HOME` when it is set. In a terminal, the script asks before it runs the command. Without a terminal, it prints the command. Set `NACRE_YES=1` to run it with `--yes`. If group membership changed, the script prints the command; log in again before you run it.

Installation asks for the user, hostname, role, time zone and locale. Then it does these steps:

1. Detects AMD graphics and initramfs images.
2. Writes the [machine template](../templates/machine/configuration.nix) and a flake that follows Nacre into `~/.config/nacre`.
3. Stages the generated files, so that Nix can see them.

To choose another checkout, use `--dir PATH`.

The new flake follows the release tag of the running `nacre`, such as `github:abnertu/nacre/v0.11.0`. A `nacre` from another commit writes `github:abnertu/nacre`, which follows `main`.

It shows a preview of the machine and asks before `nacre upgrade system`. For unattended installation, supply each value and `--yes`. Use the newest release tag, so that the machine flake follows it:

```bash
nix run github:abnertu/nacre/v0.11.0#nacre -- install --user alice --hostname box \
  --role minimal --timezone Europe/Berlin --locale en_US.UTF-8 --yes
```

Without a terminal or `--yes`, installation stops after the plan. In an existing flake, installation protects uncommitted `configuration.nix` changes, unless you pass `--force`.

For the `runner` role, select at least one public instance file with `--runner-config FILE`. Repeat that flag for each instance:

```bash
nacre install --user alice --hostname runner-host --role runner \
  --runner-config ./public/frontend.toml --runner-config ./public/dotnet.toml
```

The flag requires the `runner` role. Installation copies the selected public dependency closure into `runners/` and stages its files before building the plan.
It preserves identical destination files. Conflicting files or symlinks stop installation, including with `--force`.
Empty `.nix-config-directory` markers preserve required empty lookup directories in Git.
Keep files within the first instance's directory. Read [Runner configuration](gitlab-runner.md#public-configuration) before selecting files.

## Restore an existing machine

Set `NACRE_REPO` to the machine repository, then run the install script:

```bash
NACRE_REPO=git@github.com:you/machines.git bash <(curl -fsSL https://github.com/abnertu/nacre/releases/latest/download/install.sh)
```

`nacre install --repo` clones into an absent or empty checkout and pins the newest Nacre on the repository's channel. Then it shows the plan and asks before `nacre upgrade system`. It takes no machine options, such as `--role`. Set up the credentials for a private repository first. Before deployment, restore the necessary external state with the [backup guide](backup.md).

## Afterwards

The activated home provides `nacre`. Add hardware, home modules and optional features as [configuration](configuration.md) describes. The [fixture](../checks/fixtures/configuration.nix) shows feature composition.

To adopt the newest Nacre, run `nacre upgrade self`, or the install script again. It updates only the `nacre` input, shows the plan and asks before `switch`. Missing packages stop `switch` with exit 3; then run `nacre upgrade system`.

Your configuration stays separate from the Nacre source.
