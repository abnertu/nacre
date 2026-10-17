usage() {
  cat <<USAGE
usage: nacre [--flake PATH] [--verbose] <command> [arguments]

Deployment
  plan                     show what switch would change; changes nothing
  switch                   converge Arch, then activate the home generation
  update                   switch, also upgrading declared pacman and AUR packages
  purge                    remove managed Arch state; skips Home Manager

Inspection
  status                   checkout, last switch, home generation, pending work
  generations              list home generations
  rollback [GENERATION]    activate an earlier home generation (Arch is not rolled back)

Source
  check                    run every flake check
  build                    build the deployment without activating

Features
  ai prepare [build|model] prepare the pinned llama.cpp build and models
  runner ACTION NAME       ACTION: prepare, register, verify, status
  noctalia ACTION [ARGS]   ACTION: capture, deploy

The checkout is --flake, else \$NACRE_FLAKE, else ~/.config/nacre or ~/.config/nix.
USAGE
}

usage_error() {
  usage >&2
  exit 2
}

flake=${NACRE_FLAKE:-}
verbose=0
while (($#)); do
  case "$1" in
    --flake)
      (($# >= 2)) || usage_error
      flake=$2
      shift 2
      ;;
    --verbose)
      verbose=1
      shift
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    --version)
      version_only=1
      shift
      ;;
    -*) usage_error ;;
    *) break ;;
  esac
done

if [[ -z $flake ]]; then
  for candidate in "${XDG_CONFIG_HOME:-$HOME/.config}"/{nacre,nix}; do
    if [[ -f $candidate/flake.nix ]]; then
      flake=$candidate
      break
    fi
  done
fi

if [[ -v version_only ]]; then
  revision=$(git -C "${flake:-.}" describe --always --dirty 2>/dev/null || echo unknown)
  printf 'nacre %s (%s)\n' "$nacre_version" "$revision"
  exit 0
fi

(($#)) || usage_error
command=$1
shift

[[ -n $flake && -f $flake/flake.nix ]] || {
  printf 'nacre: no checkout found; pass --flake PATH or set NACRE_FLAKE\n' >&2
  exit 2
}

nix_args=(--show-trace --print-build-logs)
((verbose == 0)) || nix_args+=(--verbose)
nix_progress_init "$verbose"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/nacre"
profile="${XDG_STATE_HOME:-$HOME/.local/state}/nix/profiles/home-manager"
pending_dir=/var/lib/nix-config/arch

deploy() {
  local mode=$1 deployment_args=()
  case "$mode" in
    plan) deployment_args+=(--plan) ;;
    update) deployment_args+=(--update) ;;
    purge) deployment_args+=(--purge) ;;
  esac
  ((verbose == 0)) || deployment_args+=(--verbose)
  local artifact status=0
  artifact=$(nix build --no-link --print-out-paths "${nix_progress_args[@]}" "${nix_args[@]}" \
    "$flake#$deployment")
  "$artifact/bin/$deployment" "${deployment_args[@]}" || status=$?
  if ((status == 0)) && [[ $mode == switch || $mode == update ]]; then
    mkdir -p "$state_dir"
    printf '%s %s %s\n' "$(date --iso-8601=seconds)" \
      "$(git -C "$flake" describe --always --dirty 2>/dev/null || echo unknown)" \
      "$artifact" >"$state_dir/last-switch"
  fi
  exit "$status"
}

generation_numbers() {
  local link
  for link in "$profile"-*-link; do
    [[ -L $link ]] || continue
    link=${link##*/home-manager-}
    printf '%s\n' "${link%-link}"
  done | sort -n
}

current_generation() {
  local target
  target=$(readlink "$profile" 2>/dev/null) || return 0
  target=${target##*home-manager-}
  printf '%s\n' "${target%-link}"
}

case "$command" in
  plan | switch | update | purge)
    (($# == 0)) || usage_error
    deploy "$command"
    ;;
  check)
    (($# == 0)) || usage_error
    nix_exec flake check "$flake"
    ;;
  build)
    (($# == 0)) || usage_error
    nix_exec build --no-link "$flake#$deployment"
    ;;
  status)
    (($# == 0)) || usage_error
    printf 'Checkout     %s (%s)\n' "$flake" \
      "$(git -C "$flake" describe --always --dirty 2>/dev/null || echo unknown)"
    if [[ -f $state_dir/last-switch ]]; then
      read -r when revision _ <"$state_dir/last-switch"
      printf 'Last switch  %s from %s\n' "$when" "$revision"
    else
      printf 'Last switch  not recorded by nacre\n'
    fi
    printf 'Home         generation %s\n' "$(current_generation || true)"
    pending=()
    for marker in "$pending_dir"/*.pending; do
      [[ -e $marker ]] && pending+=("$(basename "$marker" .pending)")
    done
    if ((${#pending[@]})); then
      printf 'Pending      %s (rerun the interrupted command)\n' "${pending[*]}"
    else
      printf 'Pending      none\n'
    fi
    ;;
  generations)
    (($# == 0)) || usage_error
    current=$(current_generation)
    while read -r number; do
      marker=' '
      [[ $number != "$current" ]] || marker='*'
      printf '%s %4s  %s\n' "$marker" "$number" \
        "$(date -d "@$(stat -c %Y "$profile-$number-link")" '+%F %T')"
    done < <(generation_numbers)
    ;;
  rollback)
    (($# <= 1)) || usage_error
    current=$(current_generation)
    if (($# == 1)); then
      [[ $1 =~ ^[0-9]+$ ]] || usage_error
      target=$1
    else
      target=$(generation_numbers | awk -v current="$current" '$1 < current' | tail -n 1)
    fi
    [[ -n $target && -L $profile-$target-link ]] || {
      printf 'nacre: no home generation %s to roll back to\n' "${target:-before $current}" >&2
      exit 1
    }
    printf 'Activating home generation %s; Arch state is unchanged.\n' "$target" >&2
    generation=$(readlink -f "$profile-$target-link")
    export USER="${USER:-$(id -un)}"
    if grep -q -- '--driver-version' "$generation/activate"; then
      exec "$generation/activate" --driver-version 0
    fi
    exec "$generation/activate"
    ;;
  ai)
    [[ ${1:-} == prepare && $# -le 2 ]] || usage_error
    case "${2:-}" in
      '') args=() ;;
      build) args=(-- --build-only) ;;
      model) args=(-- --model-only) ;;
      *) usage_error ;;
    esac
    nix_exec_root NO_COLOR run "$flake#llama-prepare" "${args[@]}"
    ;;
  runner)
    (($# == 2)) || usage_error
    case "$1" in
      prepare) action=reconcile ;;
      register | verify | status) action=$1 ;;
      *) usage_error ;;
    esac
    preserve=NO_COLOR
    if [[ $action == register ]]; then
      [[ -n ${GITLAB_RUNNER_TOKEN:-} ]] || {
        printf 'nacre: GITLAB_RUNNER_TOKEN is required to register\n' >&2
        exit 2
      }
      preserve=GITLAB_RUNNER_TOKEN,NO_COLOR
    fi
    nix_exec_root "$preserve" run "$flake#runnerctl" -- "$action" "$2"
    ;;
  noctalia)
    [[ ${1:-} == capture || ${1:-} == deploy ]] || usage_error
    nix_exec run "$flake#noctalia-config" -- "$@"
    ;;
  *) usage_error ;;
esac
