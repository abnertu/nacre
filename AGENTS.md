# AGENTS Instructions

Nacre builds typed machine policy into a fixed Arch deployment with an embedded Home Manager generation. Keep real machines in separate flakes. Use `checks/fixtures` for this repository's machine outputs.

**Never read or print secrets or mutable application data.** Secrets include credentials, private keys, password stores, registration tokens and Noctalia keys. Keep secrets and mutable data out of Git, derivations, command arguments and unredacted logs. Use synthetic fixtures in tests.

## Git

- Write commits in [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) format: `type(scope): summary`. Use the imperative.
- For a non-trivial change, write a commit body that explains why.
- git-cliff builds `CHANGELOG.md` from these messages, so operators read the summary.
- Mark a breaking change with `!` and a `BREAKING CHANGE:` footer.
- Author commits as the user alone, without `Co-Authored-By` or other co-author trailers.
- Commit validated work as the plan progresses.
- Before you push, squash related commits of one unit into one commit to keep the history clean.
- Keep unrelated changes in separate commits.
- Push only after the user approves that push.

## Tests

- Add a test to the repo only when it guards behavior that no existing test covers.
- The test must fail when that behavior breaks. Weigh this before you add each test.
- Behavior changes and repository contracts usually qualify. Value changes, package additions and documentation usually do not.
- A reproducible bug fix gets a regression test.
- Run throwaway tests freely to check your work.
- Keep throwaway tests out of the repo unless they meet the bar above.
- Tests exercise behavior through the real entry point. They use temporary roots, fake native commands or isolated VMs.
- Delete a test that does one of these:
  - Restates values copied from source: defaults, package lists, flags, recipe names or help text.
  - Searches source text instead of running it.
  - Compares a generated value with the expression that produced it.
  - Repeats the assertion of another test.

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
- Write English docs in US English, to the [ASD-STE100](https://www.asd-ste100.org/) writing rules:
  - An instruction has 20 words or fewer. A description has 25 words or fewer.
  - Give one instruction in each sentence.
  - Write instructions in the imperative and in the active voice.
  - Use one word for one meaning, and one meaning for one word.
- Review each sentence over these limits.
- Split it if it holds more than one instruction or fact.
- A list of items can stay in one sentence.
- Make a bullet list from more than five items.
- Read [CONTEXT.md](CONTEXT.md) before you change composition or move ownership. It holds the composition model and its boundary table.
- Read the relevant [operator guide](docs/) before you change a feature.
- [README.md](README.md) is the entry point for users.
- Write all documentation in English.
- For any future non-English documentation, first write an English draft to these rules.
- Translate that draft without changing sentence boundaries or terms for concepts.
- Keep commands, paths and code unchanged.
- Use the target language's natural word order.
- Write for an operator: state behavior, commands and limits.
- Leave out background, repetition and all that the code or `--help` already says.
- When public behavior changes, update the relevant guide.
- Keep agent constraints in this file and operator procedures in the feature guides.
- When you edit the presentation of release history or measured benchmark data, keep the data.

## Ownership

Assign one owner to each resource. Feature modules contribute native resources through `arch`. Deployment consumes the merged contributions.

- Put shared options in `lib/configuration-options.nix`. Put feature options in the feature's `module.nix`.
- Express single-value rules as option types.
- Express cross-field rules as entries in `lib/configuration-assertions.nix`. For derived values, use a feature `interface.nix`.
- Use `lib.mkDefault` for baselines. Ordinary user definitions override them. Never use import order for precedence.
- Keep registries explicit. Package and service inventories live in their owning Nix source.
- Declare each Arch adapter manifest as a `TypedDict` in `schema.py` or in the single-file adapter.
- Validate manifest keys at the adapter entry point. The `adapter-manifests` check validates generated manifests to prevent drift between Nix and Python.
- Use pyright strict for production Python. Add `# pyright: standard` to each test file.
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
- Complete Arch convergence before activating the embedded home generation. Never evaluate a home again at runtime.
- The two stages share no rollback transaction.
- Stop immediately on core failures.
- An optional module can skip as `not ready` only if its required preparation never completed.
- Treat each of these conditions as an error:
  - Invalid receipts.
  - Checksum drift.
  - Ownership conflicts.
  - Missing declared core hardware.
  - Command failures.
  - Runtime drift, including a readiness change after preflight.
- Only `--update` does pacman and AUR convergence.
- Preserve kernel gates, locks and pending markers. Record the intent before a mutation, and clear it after success.
- Leave unchanged files and healthy services untouched.
- Failure diagnostics keep stdout, stderr and partial timeout output, with secrets redacted.
- `--verbose` reaches Nix, Home Manager and privileged adapters.
- Disabling a declaration only withdraws management.
- `--purge` removes the managed Arch deployment state and skips Home Manager. It keeps packages, accounts, registrations and mutable data.
- Deployment does no automatic cleanup, directory backups or garbage collection.
- Verify the prepared AI source selector, build receipt, and each model identity and checksum before services converge.
- Prepared binaries and models live outside the store.
- llama-swap, llama-server and Caddy bind only to loopback.

## Desktop

- Use UWSM as the Hyprland entry point.
- Assign one startup owner to each application.
- Pass (`programs.password-store`) owns user credential storage.
- Some applications rewrite their settings. Declare settings read-only when changes are rare and deliberate, as with fcitx5.
- For settings changed through the GUI, such as Noctalia, keep a reviewed snapshot with capture. Let `nacre doctor` report drift.
- Never capture or commit automatically.
- Hyprland and Neovim sources live outside managed runtime paths. They are pinned flake inputs that intentional lock updates adopt.
- For local worktrees, use `development.hyprlandPath` or `development.neovimPath`.

## Releases

Version releases with [Semantic Versioning 2.0.0](https://semver.org/). `VERSION` holds the version that `nacre --version` reports.

- In 0.x, a change that breaks configuration or CLI compatibility bumps the minor version.
- Mark its commit as breaking (`type(scope)!:` or a `BREAKING CHANGE:` footer). Then git-cliff flags it in the changelog.
- `just release X.Y.Z` writes `VERSION`, adds git-cliff notes to the top of `CHANGELOG.md`, commits and tags locally.
- A pushed tag publishes a GitHub release. Like each push, it needs the user's approval.

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
