set shell := ["bash", "-euo", "pipefail", "-c"]

# List the available project commands.
default:
    @just --list

# Evaluate and build every flake check with complete build logs.
check:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec flake check

# Check formatting and stable interfaces without building the full home.
check-fast:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec build --no-link \
      .#checks.x86_64-linux.source-format \
      .#checks.x86_64-linux.source-lint \
      .#checks.x86_64-linux.python-types \
      .#checks.x86_64-linux.gitlab-runner-config \
      .#checks.x86_64-linux.system-settings-interface

# Query remote Arch, LizardByte, and AUR inventories.
check-arch:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec run .#arch-switch -- --check

# Build a deployment without activation.
build deployment="arch-workstation":
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec build --no-link {{ quote(".#" + deployment) }}

# Deploy the container-test configuration into a rootless podman Arch container.
container-test *options:
    {{ quote(justfile_directory() + "/scripts/container-test.sh") }} {{ options }}

# Prepare a release commit and tag locally; pushing stays a separate step.
release version:
    #!/usr/bin/env bash
    set -euo pipefail
    version={{ quote(version) }}
    [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'usage: just release X.Y.Z\n' >&2; exit 2; }
    git diff --quiet && git diff --cached --quiet || { printf 'commit or stash changes first\n' >&2; exit 1; }
    printf '%s\n' "$version" >VERSION
    notes=$(nix run nixpkgs#git-cliff -- --unreleased --tag "v$version" --strip all)
    { head -n 2 CHANGELOG.md; printf '%s\n\n' "$notes"; tail -n +3 CHANGELOG.md; } >CHANGELOG.md.new
    mv CHANGELOG.md.new CHANGELOG.md
    git add VERSION CHANGELOG.md
    git commit -qm "chore(release): v$version"
    git tag -a "v$version" -m "Nacre $version"
    printf 'Tagged v%s. Push with: git push origin main "v%s"\n' "$version" "$version"
