# Noctalia configuration

`noctalia-config` synchronizes owned UI preferences with a reviewed snapshot at `homes/<user>/noctalia/config.toml` in the machine flake. Home Manager projects matching links. Keys and application data stay outside this workflow.

The snapshot includes wallpaper preferences. A GUI override can replace the declared wallpaper. The deploy dry run reports the conflict. [Theme templates](desktop-session.md#themes) generate the colors, and capture ignores them.

To begin, track an empty snapshot:

```bash
mkdir -p homes/alice/noctalia && touch homes/alice/noctalia/config.toml
git add homes/alice/noctalia/config.toml
```

From `configuration.nix`, select it through the home module:

```nix
users.users.alice.home.workstation.noctalia.preferencesFile = ./homes/alice/noctalia/config.toml;
```

Without this declaration, Noctalia manages its own settings. To validate a snapshot without live state:

```bash
noctalia config validate homes/alice/noctalia/config.toml
```

## Capture

```bash
nacre noctalia capture --dry-run
nacre noctalia capture
```

Capture does these steps:

1. Exports effective preferences.
2. Filters owned sections.
3. Validates a staged candidate.
4. If it changed, replaces the snapshot atomically.

Validation warnings stop capture. Capture does not stage, commit or push. Before you commit, examine labels and paths for personal information.

`noctalia-config capture --check` writes nothing and names changed sections without their values. Exit 3 means drift. Doctor runs this comparison, also after an update.

## Deploy

```bash
nacre noctalia deploy --dry-run
nacre noctalia deploy
```

Deploy builds and activates the selected home. Then it verifies owned Noctalia sections, without Arch convergence. Nacre supplies the machine checkout as `--repo` and forwards input overrides.

Conflicting GUI overrides stop deployment. To replace owned overrides deliberately, stop the shell first:

```bash
systemctl --user stop noctalia.service
nacre noctalia deploy --replace-overrides
systemctl --user start noctalia.service
```

Unowned sections do not change. Replacement writes private recovery state before it changes overrides.

## Recovery

An interrupted replacement leaves receipts and backups under `~/.local/state/nix-config/noctalia-config/`. Keep them. Stop Noctalia, then run:

```bash
nacre noctalia deploy --recover
```

Recovery restores content only while the current state matches the recorded transition. Resolve concurrent edits manually.
