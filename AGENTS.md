# AGENTS Instructions

Nacre builds typed machine policy into a fixed Arch deployment and Home Manager generation. Real machines live in separate flakes. `checks/fixtures` supplies the machine outputs of this repo.

**Never read or print secrets or mutable application data.** Secrets are credentials, private keys, password stores, registration tokens and Noctalia keys. Keep secrets and mutable data out of Git, derivations, command arguments and unredacted logs. Tests use synthetic fixtures.

## Ownership

Each resource has one owner. Feature modules contribute native resources through `arch`. Deployment consumes those merged contributions.

- Put shared options in `lib/configuration-options.nix`. Put feature options in the feature's `module.nix`.
- Express single-value rules as option types.
- Express cross-field rules as entries in `lib/configuration-assertions.nix`. For derived values, use a feature `interface.nix`.
- Precedence comes from `lib.mkDefault` baselines against ordinary user definitions, never from import order.
- Keep registries explicit. Package and service inventories live in their owning Nix source.
- Each Arch adapter declares its manifest as a `TypedDict`, in `schema.py` or in the single-file adapter.
- The adapter's entry point validates the manifest keys. The `adapter-manifests` check validates the generated manifests. Thus Nix and Python cannot drift apart.
- Production Python is pyright strict. Each test file opts down with `# pyright: standard`.
- Nix generates static, public policy.
- Python adapters and orchestration (`arch-switch`, `nacre`, `llama-prepare`) do only safe live-state reconciliation, validation and recovery.
- Use Bash only for thin entry points: the deployment wrapper, home switch, bootstrap and the container test.
- Keep secrets, runtime receipts, registration tokens and mutable data outside derivations.
- Host state keeps the `nix-config` namespace, so existing machines need no migration. The namespace covers `/var/lib/nix-config`, `60-nix-config.conf` drop-ins, `# BEGIN nix-config` blocks and receipts.
- New persistent identifiers use the `nix-config` namespace too. `nacre` names only the project, its command and state without history.
- Human accounts exist before deployment.
- Modules own service accounts. Service accounts get no home composition.
- Keep the Home Manager `stateVersion` fixed through routine updates.

## Deployment contracts

- The deployment artifact embeds the exact Home Manager activation package.
- Arch convergence completes first. Then that generation activates. Nothing evaluates a home again at runtime.
- The two stages share no rollback transaction.
- Core failures stop immediately.
- An optional module can skip as `not ready` only if its required preparation never completed.
- These are errors: invalid receipts, checksum drift, ownership conflicts, missing declared core hardware, command failures and runtime drift. Runtime drift includes a readiness change after preflight.
- Only `--update` does pacman and AUR convergence.
- Preserve kernel gates, locks and pending markers. Record the intent before a mutation, and clear it after success.
- Leave unchanged files and healthy services untouched.
- Failure diagnostics keep stdout, stderr and partial timeout output, with secrets redacted.
- `--verbose` reaches Nix, Home Manager and privileged adapters.
- Disabling a declaration only withdraws management.
- `--purge` removes the managed Arch deployment state and skips Home Manager. It keeps packages, accounts, registrations and mutable data.
- Deployment does no automatic cleanup, directory backups or garbage collection.
- Before services converge, AI preparation verifies the source selector, the build receipt and each model identity and checksum.
- Prepared binaries and models live outside the store.
- llama-swap, llama-server and Caddy bind only to loopback.

## Desktop

- UWSM is the Hyprland entry point.
- Each application has one startup owner.
- Pass (`programs.password-store`) owns user credential storage.
- Some applications rewrite their settings. If such settings change rarely and on purpose (fcitx5), declare them read-only.
- If they change in the application's GUI (Noctalia), keep a reviewed snapshot with capture. Let `nacre doctor` report the drift.
- Never capture or commit automatically.
- Hyprland and Neovim sources live outside managed runtime paths. They are pinned flake inputs that intentional lock updates adopt.
- For local worktrees, use `development.hyprlandPath` or `development.neovimPath`.

## Tests

- Add a test to the repo only when it guards behaviour that no existing test covers.
- The test must fail when that behaviour breaks. Weigh this before you add each test.
- Behaviour changes and the contracts above usually qualify. Value changes, package additions and documentation usually do not.
- A reproducible bug fix gets a regression test.
- Run throwaway tests freely to check your work.
- Keep throwaway tests out of the repo unless they meet the bar above.
- Tests exercise behaviour through the real entry point. They use temporary roots, fake native commands or isolated VMs.
- Delete a test that does one of these:
  - Restates values copied from source: defaults, package lists, flags, recipe names or help text.
  - Searches source text instead of running it.
  - Compares a generated value with the expression that produced it.
  - Repeats the assertion of another test.

## Validation

Format changed Nix files with `nixfmt <files>`, never with `nix fmt`. For composition, adapter or test changes, run these from the repo root:

```bash
just check-fast
just check
just build
git diff --check
```

To verify a change against a real machine, build or plan from its machine flake. Use `nacre --override-input nacre path:<this checkout>`. Never commit that override.

These commands build without activation.

- For deployment or adapter changes, also run `just container-test` when podman is available. It deploys into a disposable container, never into the host.
- Deployment, preparation, registration, package installation and service operations change live state. Get the user's go-ahead before them.
- For documentation-only edits, run `nix build .#checks.x86_64-linux.source-lint` and `git diff --check`. The source lint checks relative links and anchors.

## Git

- Write commits in [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) format: `type(scope): summary`, in the imperative.
- For a non-trivial change, write a commit body that explains why.
- git-cliff builds `CHANGELOG.md` from these messages, so operators read the summary.
- Mark a breaking change with `!` and a `BREAKING CHANGE:` footer.
- Author commits as the user alone, without `Co-Authored-By` or other co-author trailers.
- Commit validated work as the plan progresses.
- Before you push, squash related commits of one unit into one commit to keep the history clean.
- Keep unrelated changes in separate commits.
- Push only after the user approves that push.

## Releases

Version releases with [Semantic Versioning 2.0.0](https://semver.org/). `VERSION` holds the version that `nacre --version` reports.

- In 0.x, a change that breaks configuration or CLI compatibility bumps the minor version.
- Mark its commit as breaking (`type(scope)!:` or a `BREAKING CHANGE:` footer). Then git-cliff flags it in the changelog.
- `just release X.Y.Z` writes `VERSION`, adds git-cliff notes to the top of `CHANGELOG.md`, commits and tags locally.
- A pushed tag publishes a GitHub release. Like each push, it needs the user's approval.

## CI

- Keep a CI check only when it catches a concrete failure that no existing check covers.
- Identify that failure before you add or keep the check.
- Apply the test rules to CI checks too.
- Run the repo's entry points against real inputs or isolated fixtures.
- Reject duplicate checks, source-text assertions, copied inventories and checks that only prove that a command or file exists.
- Name each workflow, job and step by its target and its action.
- Propagate command failures.
- Count a missing prerequisite or skipped required coverage as a failure.
- After you change these rules, audit the repo against them.
- Validate changes locally. Then verify the required CI on the pushed commit.
- Report each uncovered contract and each unavailable check.

## Docs

- Keep each doc concise and plain. Each sentence must carry information.
- Write English docs to the [ASD-STE100](https://www.asd-ste100.org/) writing rules:
  - An instruction has 20 words or fewer. A description has 25 words or fewer.
  - Give one instruction in each sentence.
  - Write instructions in the imperative and in the active voice.
  - Use one word for one meaning, and one meaning for one word.
- Read [CONTEXT.md](CONTEXT.md) before you change composition or move ownership. It holds the composition model and its boundary table.
- Read the relevant [operator guide](docs/) before you change a feature.
- [README.md](README.md) is the entry point for users.
- Write all documentation in English.
- Write for an operator: state behaviour, commands and limits.
- Leave out background, repetition and all that the code or `--help` already says.
- When public behaviour changes, update the relevant guide.
- Keep agent constraints in this file and operator procedures in the feature guides.
- When you edit the presentation of release history or measured benchmark data, keep the data.
