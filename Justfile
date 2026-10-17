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

# Prepare the pinned llama.cpp build and all declared models.
prepare-ai mode="":
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    case {{ quote(mode) }} in
      '') args=() ;;
      build) args=(-- --build-only) ;;
      model) args=(-- --model-only) ;;
      *) printf '%s\n' 'usage: just prepare-ai [build|model]' >&2; exit 2 ;;
    esac
    nix_exec_root NO_COLOR run .#llama-prepare "${args[@]}"

# Reconcile one configured GitLab Runner instance before registration.
prepare-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec_root NO_COLOR run .#runnerctl -- reconcile {{ quote(instance) }}

# Register and verify one prepared GitLab Runner. Requires GITLAB_RUNNER_TOKEN.
initialize-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    [[ -n ${GITLAB_RUNNER_TOKEN:-} ]] || {
      printf '%s\n' 'GITLAB_RUNNER_TOKEN is required' >&2
      exit 2
    }
    nix_exec_root GITLAB_RUNNER_TOKEN,NO_COLOR run .#runnerctl -- register {{ quote(instance) }}

# Verify a configured GitLab Runner instance.
verify-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec_root NO_COLOR run .#runnerctl -- verify {{ quote(instance) }}

# Show the current state of a configured GitLab Runner instance.
status-runner instance:
    #!/usr/bin/env bash
    set -euo pipefail
    source {{ quote(justfile_directory() + "/lib/cli/nix.sh") }}
    nix_exec_root NO_COLOR run .#runnerctl -- status {{ quote(instance) }}

# Build and activate the Arch workstation; `plan` previews changes without making them.
arch-workstation option1="" option2="":
    #!/usr/bin/env bash
    set -euo pipefail
    readonly usage='usage: just arch-workstation [plan | update | purge] [verbose]'
    options=({{ quote(option1) }} {{ quote(option2) }})
    deployment_args=()
    nix_args=(--show-trace --print-build-logs)
    update_seen=0
    purge_seen=0
    plan_seen=0
    verbose_seen=0
    for option in "${options[@]}"; do
      case "$option" in
        '') ;;
        update)
          (( update_seen == 0 && plan_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
          update_seen=1
          ;;
        plan)
          (( plan_seen == 0 && update_seen == 0 && purge_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
          deployment_args+=(--plan)
          plan_seen=1
          ;;
        purge)
          (( purge_seen == 0 && update_seen == 0 && plan_seen == 0 )) || { printf '%s\n' "$usage" >&2; exit 2; }
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
