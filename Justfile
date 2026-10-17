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
