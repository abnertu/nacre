# Backup and restore

The flake rebuilds configuration. Deployment creates no backups. Keep irreplaceable external state on encrypted media, with its original owner and mode. Keep secrets outside Git and the Nix store.

## Required state

| State | Location | Loss consequence |
| --- | --- | --- |
| GPG private keys | `~/.gnupg/` | Password store and Git credentials cannot be decrypted |
| Password store | `~/.password-store/` | Stored passwords are lost |
| SSH keys | `~/.ssh/` | Keys must be replaced at every authorized service |
| Noctalia storage key and encrypted data | Key: `~/.local/share/noctalia/file-key-v1/master-key` | A newly generated key cannot decrypt old data |
| Hotspot connection | `/etc/NetworkManager/system-connections/` | AP and WPA credentials must be recreated |

Machine extensions can add required state. Follow their own backup procedures.

## Rebuildable state

| State | Location | Recovery cost |
| --- | --- | --- |
| Tailscale identity | `/var/lib/tailscale/` | Authenticate as a new node |
| AI binaries and models | Declared native install/model paths | Rebuild and download through `nacre ai prepare` |
| Tool sessions | Tool-owned login directories | Authenticate again |
| Input learning | `~/.local/share/fcitx5/` | Relearn phrases and order |

Before you reinstall, review uncaptured Noctalia preferences. [Capture](noctalia-config.md#capture) and commit the preferences that you want to keep. The Nix store, home generations and deployment pending markers are not restore inputs.

## Restore order

1. Install Arch and recreate the login account in `wheel`.
2. Clone the machine flake and run the [bootstrap](deployment.md#bootstrap). For a new machine, use [installation](install.md).
3. Restore required external state with its original metadata, including extension-owned state.
4. Review `nacre plan`, then run `nacre update`.
5. Prepare AI and any machine extensions that need a separate setup step.
