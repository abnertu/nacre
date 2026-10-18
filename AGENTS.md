# AGENTS Instructions

Nacre: an operator-controlled Nix layer over existing Arch Linux + Hyprland machines; `hosts/arch` is the maintainer's own machine. Nix evaluates typed policy into a fixed deployment artifact, Arch adapters reconcile live state, then the prebuilt Home Manager generation activates. Read [CONTEXT.md](CONTEXT.md) before changing composition, and the feature's guide in [`docs/`](docs/) before editing that feature.

**Never read or print credentials, private keys, password stores, Runner tokens, Noctalia keys or mutable application data.** Keep them out of Git, derivations, command arguments and unredacted logs; tests use synthetic fixtures.

## Ownership

Each resource has exactly one owner:

| Path | Owns |
| --- | --- |
| `lib/` | Evaluation, normalization (`lib/eval-configuration.nix`), deployment composition and machine flake outputs (`lib/mk-flake.nix`: fixed names such as `#deployment`) |
| `templates/machine/` | The flake and configuration `nacre install` writes for a new machine |
| `roles/` | Baseline compositions at priority 1100, below host defaults |
| `hosts/` | Identity and baselines, always via `lib.mkDefault` |
| `platforms/<distro>/` | Native realization and its contribution interface (`platforms/arch/module.nix`); distro-specific code stays here so other distros can sit beside `arch/` |
| `modules/` | Feature modules: each `module.nix` declares its options and contributes its own `arch.*` packages, groups and units (registry: `modules/default.nix`) |
| `profiles/`, `homes/` | Home Manager composition |

- Shared options live in `lib/configuration-options.nix`, feature options in their `module.nix`. Express single-value rules as option types and cross-field rules as entries in `lib/configuration-assertions.nix` (or a feature `interface.nix` for derived values). Precedence comes from `lib.mkDefault` baselines versus ordinary user definitions, never import order.
- Deployment code reads merged contributions from the evaluated `arch` option; a new feature adds its native names there instead of wiring them through `lib/mk-deployment.nix`.
- Registries stay explicit. Package and service inventories live in their owning Nix source.
- Each Arch adapter declares its manifest as a `TypedDict` (`schema.py`, or in the single-file adapter itself); its entry point validates the manifest's keys, and the `adapter-manifests` check validates the generated manifests, so Nix and Python cannot drift apart. Production Python is pyright strict; each test file opts down with `# pyright: standard`.
- Static, public policy is Nix-generated. Python adapters and orchestration (`arch-switch`, `nacre`, `llama-prepare`) do safe live-state reconciliation, validation and recovery only; Bash is limited to thin entry points such as the deployment wrapper, home switch, bootstrap and the container test. Secrets, runtime receipts, registration tokens and mutable data stay outside derivations.
- Host state keeps the `nix-config` namespace (`/var/lib/nix-config`, `60-nix-config.conf` drop-ins, `# BEGIN nix-config` blocks, receipts) so existing machines need no migration. New persistent identifiers use it too; `nacre` names only the project, its command and state without history.
- Human accounts exist before deployment. Modules own service accounts, which get no home composition. Home Manager `stateVersion` stays fixed through routine updates.

## Deployment contracts

- The deployment artifact embeds the exact Home Manager activation package. Arch convergence completes first, then that generation activates; nothing reevaluates a home at runtime. The two stages share no rollback transaction.
- Core failures stop immediately. An optional module may skip as `not ready` only if its required preparation has never completed. Invalid receipts, checksum drift, ownership conflicts, missing declared core hardware, command failures and runtime drift — including readiness changing after preflight — are errors.
- Only `--update` performs pacman/AUR convergence. Preserve kernel gates, locks and pending markers: record intent before mutation, clear it after success, leave unchanged files and healthy services untouched.
- Failure diagnostics keep stdout, stderr and partial timeout output, with secrets redacted. `--verbose` reaches Nix, Home Manager and privileged adapters.
- Disabling a declaration withdraws management only. `--purge` removes managed Arch deployment state, keeps packages, accounts, Runner registrations and mutable data, and skips Home Manager. Deployment performs no automatic cleanup, directory backups, garbage collection or Runner purge.
- AI preparation verifies the source selector, build receipt and every model identity/checksum before services converge. Prepared binaries and models live outside the store; llama-swap, llama-server and Caddy bind loopback only. Runner reconcile, registration and verification stay separate from workstation deployment.

## Desktop

- UWSM is the Hyprland entry point; each application has one startup owner.
- Pass (`programs.password-store`) owns user credential storage.
- Hyprland and Neovim sources live outside managed runtime paths: pinned flake inputs adopted through intentional lock updates, or local worktrees via `development.hyprlandPath` / `development.neovimPath`.

## Tests

Decide per change whether a test is warranted. A test earns its place when it would catch a realistic regression in behavior or in a contract above; value tweaks, package additions and documentation usually need none. A reproducible bug fix gets a regression test.

Tests exercise behavior through the real entry point, using temporary roots, fake native commands or isolated VMs. A test is invalid, and gets deleted when found, if it:

- restates values copied from source (defaults, package lists, flags, recipe names, help text);
- greps source text instead of running it;
- compares a generated value with the expression that produced it;
- repeats an assertion another test already makes;
- cannot fail.

## Validation

Format Nix with `nixfmt <files>` (or `find . -name '*.nix' -print0 | xargs -0 nixfmt`), never `nix fmt`. For composition, adapter or test changes, run from the repository root:

```bash
just check-fast
just check
just build
nix build --no-link --show-trace --print-build-logs \
  '.#homeConfigurations."abnertu@arch".activationPackage'
git diff --check
```

These build without activating. For deployment or adapter changes, also run `just container-test` when podman is available: it deploys into a disposable container, never the host. Deployment, preparation, registration, package installation and service operations change live state and need the user's go-ahead. For documentation-only edits, run `nix build .#checks.x86_64-linux.source-lint` (relative links and anchors) and `git diff --check`.

## Git

- Commit validated work freely. Push only when the user explicitly asks.
- Messages follow Conventional Commits (`type(scope): summary`, imperative), with a body explaining why for non-trivial changes.
- Squash unpushed commits that make related changes to the same unit into one; keep unrelated changes separate.
- Commits carry the configured Git author only: no `Co-Authored-By` or other attribution trailers.

## Releases

`VERSION` holds the semantic version that `nacre --version` reports. While in 0.x, a change that breaks configuration or CLI compatibility bumps the minor version. `just release X.Y.Z` writes `VERSION`, prepends git-cliff notes to `CHANGELOG.md`, commits and tags locally. Pushing the tag publishes a GitHub release, so it needs the user's go-ahead like any push.

## Documentation

[README.md](README.md) is the entry point, [CONTEXT.md](CONTEXT.md) the composition model and `docs/` the operator procedures. All documentation is English. Write for an operator: state behavior, commands and limits; cut background, repetition and anything the code or `--help` already says. Update the relevant guide when public behavior changes. Agent constraints live only in this file.
