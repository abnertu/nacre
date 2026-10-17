usage() {
  cat <<USAGE
usage: nacre [--flake PATH] [--verbose] <command> [arguments]

Setup
  install [OPTIONS]        write configuration.nix for this machine, then plan and update
                           --user NAME --hostname NAME --role minimal|workstation
                           --timezone ZONE --locale LOCALE --yes --force

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
# Tests point installation at a fake root.
install_root=${NACRE_INSTALL_ROOT:-}

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

install_machine() {
  local user=${USER:-} hostname timezone locale role=workstation yes=0 force=0
  hostname=$(cat "$install_root/etc/hostname" 2>/dev/null || uname -n)
  timezone=$(timedatectl show --property=Timezone --value 2>/dev/null || echo UTC)
  locale=${LANG:-en_US.UTF-8}
  locale=${locale/.utf8/.UTF-8}
  while (($#)); do
    case "$1" in
      --user | --hostname | --role | --timezone | --locale)
        (($# >= 2)) || usage_error
        local key=${1#--}
        printf -v "$key" '%s' "$2"
        shift 2
        ;;
      --yes) yes=1; shift ;;
      --force) force=1; shift ;;
      *) usage_error ;;
    esac
  done

  if ((yes == 0)) && [[ -t 0 ]]; then
    local answer
    for key in user hostname role timezone locale; do
      read -r -p "$key [${!key}]: " answer
      [[ -z $answer ]] || printf -v "$key" '%s' "$answer"
    done
  fi

  local entry description
  [[ $user =~ ^[a-z][a-z0-9_-]*$ ]] || install_error "invalid user name: $user"
  [[ $hostname =~ ^[a-z][a-z0-9_-]*$ ]] || install_error "invalid hostname: $hostname"
  [[ $role == minimal || $role == workstation ]] || install_error "unknown role: $role"
  [[ $timezone =~ ^[A-Za-z0-9_+/-]+$ ]] || install_error "invalid time zone: $timezone"
  [[ $locale =~ ^[A-Za-z0-9_@.-]+$ ]] || install_error "invalid locale: $locale"
  entry=$(getent passwd "$user") || install_error "create the account $user before installing"
  [[ $(cut -d: -f6 <<<"$entry") == "/home/$user" ]] || install_error "$user must live in /home/$user"
  getent group wheel | cut -d: -f4 | tr ',' '\n' | grep -qx "$user" ||
    install_error "$user must be in the wheel group"
  description=$(cut -d: -f5 <<<"$entry" | cut -d, -f1)
  description=${description:-$user}
  description=${description//[\\\"\$]/}

  local graphics=generic images=() image
  if lspci 2>/dev/null | grep -E 'VGA|3D|Display' | grep -qiE 'AMD|ATI'; then graphics=amd; fi
  for image in "$install_root"/boot/initramfs-*.img; do
    [[ -e $image && $image != *fallback* ]] && images+=("\"${image#"$install_root"}\"")
  done
  ((${#images[@]})) || install_error "no initramfs image under /boot"

  local target=$flake/configuration.nix
  if [[ -e $target ]] && ((force == 0)) &&
    ! git -C "$flake" diff --quiet HEAD -- configuration.nix 2>/dev/null; then
    install_error "configuration.nix has uncommitted changes; commit them or pass --force"
  fi
  local content
  content=$(<"$flake/templates/configuration.nix")
  content=${content//@role@/$role}
  content=${content//@hostname@/$hostname}
  content=${content//@timezone@/$timezone}
  content=${content//@locale@/$locale}
  content=${content//@description@/$description}
  content=${content//@graphics@/$graphics}
  content=${content//@username@/$user}
  content=${content//@images@/${images[*]}}
  printf '%s\n' "$content" >"$target"
  printf 'Wrote %s:\n\n%s\n\n' "$target" "$content" >&2

  "$0" --flake "$flake" plan
  if ((yes == 0)); then
    local confirm=n
    [[ ! -t 0 ]] || read -r -p 'Apply this plan with nacre update? [y/N] ' confirm
    [[ $confirm == [yY]* ]] || { printf 'Not applied. Run nacre update when ready.\n' >&2; exit 0; }
  fi
  exec "$0" --flake "$flake" update
}

install_error() {
  printf 'nacre install: %s\n' "$1" >&2
  exit 2
}

case "$command" in
  install)
    install_machine "$@"
    ;;
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
