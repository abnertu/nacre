set shell := ["bash", "-euo", "pipefail", "-c"]

# List the available project commands.
default:
    @just --list

# Evaluate and build every flake check with complete build logs.
check:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec nix "${nix_progress_args[@]}" flake check --show-trace --print-build-logs

# Check formatting and stable interfaces without building the full home.
check-fast:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec nix "${nix_progress_args[@]}" build --no-link --show-trace --print-build-logs \
      .#checks.x86_64-linux.source-format \
      .#checks.x86_64-linux.python-types \
      .#checks.x86_64-linux.gitlab-runner-interface \
      .#checks.x86_64-linux.system-settings-interface

# Query remote Arch, LizardByte, and AUR inventories.
check-arch:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec nix "${nix_progress_args[@]}" run --show-trace --print-build-logs .#arch-switch -- --check

# Build a deployment without activation.
build deployment="arch-workstation":
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec nix "${nix_progress_args[@]}" build --no-link --show-trace --print-build-logs {{ quote(".#" + deployment) }}

# Deploy the container-test configuration into a rootless podman Arch container.
container-test *options:
    {{ quote(justfile_directory() + "/scripts/container-test.sh") }} {{ options }}

# Prepare the pinned llama.cpp build and all declared models.
prepare-ai mode="":
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    case {{ quote(mode) }} in
      '') args=() ;;
      build) args=(-- --build-only) ;;
      model) args=(-- --model-only) ;;
      *) printf '%s\n' 'usage: just prepare-ai [build|model]' >&2; exit 2 ;;
    esac
    exec sudo --preserve-env=NO_COLOR nix "${nix_progress_args[@]}" \
      --extra-experimental-features 'nix-command flakes' run --show-trace --print-build-logs .#llama-prepare "${args[@]}"

# Reconcile one configured GitLab Runner instance before registration.
prepare-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec sudo --preserve-env=NO_COLOR nix "${nix_progress_args[@]}" \
      --extra-experimental-features 'nix-command flakes' run --show-trace --print-build-logs .#runnerctl -- reconcile {{ quote(instance) }}

# Register and verify one prepared GitLab Runner. Requires GITLAB_RUNNER_TOKEN.
initialize-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    [[ -n ${GITLAB_RUNNER_TOKEN:-} ]] || {
      printf '%s\n' 'GITLAB_RUNNER_TOKEN is required' >&2
      exit 2
    }
    exec sudo --preserve-env=GITLAB_RUNNER_TOKEN,NO_COLOR \
      nix "${nix_progress_args[@]}" --extra-experimental-features 'nix-command flakes' run --show-trace --print-build-logs .#runnerctl -- register {{ quote(instance) }}

# Verify a configured GitLab Runner instance.
verify-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec sudo --preserve-env=NO_COLOR nix "${nix_progress_args[@]}" \
      --extra-experimental-features 'nix-command flakes' run --show-trace --print-build-logs .#runnerctl -- verify {{ quote(instance) }}

# Show the current state of a configured GitLab Runner instance.
status-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init
    exec sudo --preserve-env=NO_COLOR nix "${nix_progress_args[@]}" \
      --extra-experimental-features 'nix-command flakes' run --show-trace --print-build-logs .#runnerctl -- status {{ quote(instance) }}

# Build and activate the Arch workstation; combine update, purge and verbose as needed.
arch-workstation option1="" option2="":
    #!/usr/bin/env bash
    set -euo pipefail
    readonly usage='usage: just arch-workstation [update] [purge] [verbose]'
    options=({{ quote(option1) }} {{ quote(option2) }})
    deployment_args=()
    nix_args=(--show-trace --print-build-logs)
    update_seen=0
    purge_seen=0
    verbose_seen=0
    for option in "${options[@]}"; do
      case "$option" in
        '') ;;
        update)
          (( update_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
          update_seen=1
          ;;
        purge)
          (( purge_seen == 0 && update_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
          deployment_args+=(--purge)
          purge_seen=1
          ;;
        verbose)
          (( verbose_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
          verbose_seen=1
          ;;
        *) printf '%s\n' "$usage" >&2; exit 2 ;;
      esac
    done
    (( update_seen == 0 )) || deployment_args+=(--update)
    if (( verbose_seen )); then
      deployment_args+=(--verbose)
      nix_args+=(--verbose)
    fi
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_progress_init "$verbose_seen"
    nix build --no-link "${nix_progress_args[@]}" "${nix_args[@]}" .#arch-workstation
    if ((${#deployment_args[@]})); then
      exec nix run "${nix_progress_args[@]}" "${nix_args[@]}" .#arch-workstation -- "${deployment_args[@]}"
    else
      exec nix run "${nix_progress_args[@]}" "${nix_args[@]}" .#arch-workstation
    fi
