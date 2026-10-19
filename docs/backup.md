# Backup

The repository rebuilds the workstation. Back up the state outside it that cannot be rebuilt, or is expensive to rebuild. Deployment never makes backups. Most of these files hold secrets: use encrypted media and keep them out of Git.

## Required

Lost state here cannot be recovered or invalidates existing data.

| State | Location | If lost |
| --- | --- | --- |
| GPG private keys | `~/.gnupg/` | `pass` and the Git credential store cannot be decrypted |
| Password store | `~/.password-store/` | All passwords are gone |
| SSH keys | `~/.ssh/` | Regenerate and update public keys everywhere |
| Noctalia storage key | `~/.local/share/noctalia/file-key-v1/master-key` | Deployment creates a new key; old encrypted data is unreadable |
| Hotspot connection (with WPA password) | `/etc/NetworkManager/system-connections/` | Recreate the AP connection |

## Rebuildable, but saves time

| State | Location | Without a backup |
| --- | --- | --- |
| Tailscale node identity | `/var/lib/tailscale/` | Log in again; the node joins as a new identity |
| AI binaries and models | llama.cpp install and model paths (see the AI module) | `nacre ai prepare` rebuilds and redownloads several GB |
| Tool logins | e.g. `~/.codex/`, OneDrive refresh tokens | Log in again |
| Input method learning | `~/.local/share/fcitx5/` | Chewing relearns phrases and their order |

Noctalia GUI changes reach the repository only through a capture: before reinstalling, resolve any `nacre doctor` warning with [`nacre noctalia capture`](noctalia-config.md#capture) and commit.

The repository's own configuration, the Nix store, Home Manager generations and pending markers in `/var/lib/nix-config/arch/` need no backup.

## Restore order

1. Install Arch and create the same user account (in `wheel`).
2. Clone your repository and run the [bootstrap](deployment.md#bootstrap); a new machine follows the [install guide](install.md) instead.
3. Restore the required files with their original owner and mode, including those your machine's extensions document.
4. Preview with `nacre plan`, then deploy with `nacre update`.
5. Run `nacre ai prepare` and any preparation your extensions need.
