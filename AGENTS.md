# AGENTS Instructions

Nacre builds typed machine policy into a fixed Arch deployment and Home Manager generation. Real machines live in separate flakes; `checks/fixtures` supplies this repository's machine outputs. Read [CONTEXT.md](CONTEXT.md) before changing composition and the relevant [operator guide](docs/) before changing a feature.

**Never read or print credentials, private keys, password stores, registration tokens, Noctalia keys or mutable application data.** Keep them out of Git, derivations, command arguments and unredacted logs; tests use synthetic fixtures.

## Ownership

Each resource has one owner. Feature modules contribute native resources through `arch`; deployment consumes those merged contributions. Read the boundary table in [CONTEXT.md](CONTEXT.md) before moving ownership.

- Shared options live in `lib/configuration-options.nix`, feature options in their `module.nix`. Express single-value rules as option types and cross-field rules as entries in `lib/configuration-assertions.nix` (or a feature `interface.nix` for derived values). Precedence comes from `lib.mkDefault` baselines versus ordinary user definitions, never import order.
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
- Disabling a declaration withdraws management only. `--purge` removes managed Arch deployment state, keeps packages, accounts, registrations and mutable data, and skips Home Manager. Deployment performs no automatic cleanup, directory backups, or garbage collection.
- AI preparation verifies the source selector, build receipt and every model identity/checksum before services converge. Prepared binaries and models live outside the store; llama-swap, llama-server and Caddy bind loopback only.

## Desktop

- UWSM is the Hyprland entry point; each application has one startup owner.
- Pass (`programs.password-store`) owns user credential storage.
- Settings an application rewrites: declare them read-only when they change rarely and on purpose (fcitx5); keep a reviewed snapshot with capture when they change in the application's GUI (Noctalia), and let `nacre doctor` report the drift. Never capture or commit automatically.
- Hyprland and Neovim sources live outside managed runtime paths: pinned flake inputs adopted through intentional lock updates, or local worktrees via `development.hyprlandPath` / `development.neovimPath`.

## Tests

- A test enters the repo only when it guards behaviour no existing test covers and fails when that behaviour breaks. Weigh this before adding each one: behaviour changes and contracts above usually qualify; value tweaks, package additions and documentation usually do not. A reproducible bug fix gets a regression test.
- Run throwaway tests freely to check your work; keep them out of the repo unless they pass that bar.
- Tests exercise behaviour through the real entry point, using temporary roots, fake native commands or isolated VMs. Delete any test found to restate values copied from source (defaults, package lists, flags, recipe names, help text), grep source text instead of running it, compare a generated value with the expression that produced it, or repeat another test's assertion.

## Validation

Format changed Nix files with `nixfmt <files>`, never `nix fmt`. For composition, adapter or test changes, run from the repository root:

```bash
just check-fast
just check
just build
git diff --check
```

To verify a change against a real machine, build or plan from its machine flake with `nacre --override-input nacre path:<this checkout>`; never commit that override.

These build without activating. For deployment or adapter changes, also run `just container-test` when podman is available: it deploys into a disposable container, never the host. Deployment, preparation, registration, package installation and service operations change live state and need the user's go-ahead. For documentation-only edits, run `nix build .#checks.x86_64-linux.source-lint` (relative links and anchors) and `git diff --check`.

## Git

- Write commits in [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) format (`type(scope): summary`, imperative), with a body explaining why for non-trivial changes. git-cliff builds `CHANGELOG.md` from these messages, so the summary is what operators read.
- Author commits as the user alone, with no `Co-Authored-By` or other co-author trailers.
- Commit validated work as the plan progresses. Before pushing, squash related commits to the same unit into one to keep history clean; keep unrelated changes separate.
- Push only after the user approves that push.

## Releases

Version releases with [Semantic Versioning 2.0.0](https://semver.org/). `VERSION` holds the version `nacre --version` reports; while in 0.x, a change that breaks configuration or CLI compatibility bumps the minor version; mark its commit breaking (`type(scope)!:` or a `BREAKING CHANGE:` footer) so git-cliff flags it in the changelog. `just release X.Y.Z` writes `VERSION`, prepends git-cliff notes to `CHANGELOG.md`, commits and tags locally. Pushing the tag publishes a GitHub release, so it needs the user's approval like any push.

## CI

- Keep a CI check only when it catches a concrete failure no existing check covers; identify that failure before adding or retaining it. Apply the test admission rule to CI too.
- Run repository entry points against real inputs or isolated fixtures. Reject duplicate checks, source-text assertions, copied inventories and checks that only prove a command or file exists.
- Name workflows, jobs and steps by their target and action. Propagate command failures; missing prerequisites and skipped required coverage cannot count as success.
- After changing these rules, audit the repository against them. Validate locally, then verify required CI on the pushed commit; report any uncovered contract or unavailable check.

## Docs

- Keep this file, `README.md` and every other doc concise and plain: each sentence carries information, with no filler.
- [README.md](README.md) is the entry point for users, [CONTEXT.md](CONTEXT.md) the composition model and `docs/` the operator procedures. All documentation is English.
- Write for an operator: state behaviour, commands and limits; leave out background, repetition and anything the code or `--help` already says. Update the relevant guide when public behaviour changes.
- Keep agent constraints here and operator procedures in the feature guides. Preserve release history and measured benchmark data when editing their presentation.
