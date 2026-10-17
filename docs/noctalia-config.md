# Noctalia config

`noctalia-config` syncs reviewed UI preferences between Noctalia's live settings and the snapshot `homes/abnertu/noctalia/config.toml`; Home Manager manages the matching links. Encryption keys and application data are out of scope; see [desktop session](desktop-session.md).

The snapshot is the single source of Noctalia's visual preferences, including the `wallpaper` section. Picking a wallpaper in the GUI writes an override that takes precedence over the declared default; `deploy --dry-run` detects the conflict.

Colors are not captured. Noctalia's templates write the theme files at runtime and follow the wallpaper; see [themes](desktop-session.md#themes).

Validate source without reading live state:

```bash
noctalia config validate homes/abnertu/noctalia/config.toml
```

## Capture

```bash
nix run .#noctalia-config -- capture --dry-run
nix run .#noctalia-config -- capture
```

Capture exports the effective settings, keeps only the UI sections it owns, validates a staged candidate and atomically updates the snapshot when it differs. It never stages, commits or pushes. Review the diff before committing: labels and paths may contain personal data. Capture stops on validation warnings.

## Deploy

```bash
nix run .#noctalia-config -- deploy --dry-run
nix run .#noctalia-config -- deploy
```

Deploy builds and activates the selected Home Manager configuration, then verifies the managed Noctalia sections; it does not run Arch convergence. It stops when a GUI override conflicts. To replace the overrides it owns, stop Noctalia first:

```bash
systemctl --user stop noctalia.service
nix run .#noctalia-config -- deploy --replace-overrides
systemctl --user start noctalia.service
```

Sections it does not own are never modified. It writes private recovery state before changing overrides.

## Recovery

Recovery state lives in `~/.local/state/nix-config/noctalia-config/`. If a replacement was interrupted, keep the receipt and backup, stop Noctalia and run:

```bash
nix run .#noctalia-config -- deploy --recover
```

It restores saved content only if the current state still matches the recorded transition; concurrent edits need manual handling.
