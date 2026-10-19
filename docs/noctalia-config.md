# Noctalia config

`noctalia-config` syncs reviewed UI preferences between Noctalia's live settings and a snapshot in your machine flake at `homes/<user>/noctalia/config.toml`; Home Manager manages the matching links. Encryption keys and application data are out of scope; see [desktop session](desktop-session.md).

The snapshot is the single source of Noctalia's visual preferences, including the `wallpaper` section. Picking a wallpaper in the GUI writes an override that takes precedence over the declared default; `deploy --dry-run` detects the conflict.

Colors are not captured. Noctalia's templates write the theme files at runtime and follow the wallpaper; see [themes](desktop-session.md#themes).

Start a snapshot by tracking an empty file and pointing Home Manager at it, then capture:

```bash
mkdir -p homes/alice/noctalia && touch homes/alice/noctalia/config.toml
git add homes/alice/noctalia/config.toml
```

```nix
users.users.alice.home.workstation.noctalia.preferencesFile = ./homes/alice/noctalia/config.toml;
```

Without a snapshot, Noctalia keeps its own settings. Validate a snapshot without reading live state:

```bash
noctalia config validate homes/alice/noctalia/config.toml
```

## Capture

```bash
nacre noctalia capture --dry-run
nacre noctalia capture
```

`noctalia-config capture --check` compares the live preferences with the snapshot and writes nothing; it names the changed sections, never their values, and exits 3 when they differ. `nacre doctor`, and so every `nacre update`, runs it.

Capture exports the effective settings, keeps only the UI sections it owns, validates a staged candidate and atomically updates the snapshot when it differs. It never stages, commits or pushes. Review the diff before committing: labels and paths may contain personal data. Capture stops on validation warnings.

## Deploy

```bash
nacre noctalia deploy --dry-run
nacre noctalia deploy
```

Deploy builds and activates the selected Home Manager configuration, then verifies the managed Noctalia sections; it does not run Arch convergence. `nacre` passes the machine flake as `--repo`, and `nacre --override-input … noctalia deploy` builds the home with the same overrides as `switch`. It stops when a GUI override conflicts. To replace the overrides it owns, stop Noctalia first:

```bash
systemctl --user stop noctalia.service
nacre noctalia deploy --replace-overrides
systemctl --user start noctalia.service
```

Sections it does not own are never modified. It writes private recovery state before changing overrides.

## Recovery

Recovery state lives in `~/.local/state/nix-config/noctalia-config/`. If a replacement was interrupted, keep the receipt and backup, stop Noctalia and run:

```bash
nacre noctalia deploy --recover
```

It restores saved content only if the current state still matches the recorded transition; concurrent edits need manual handling.
