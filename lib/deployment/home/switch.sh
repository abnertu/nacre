unset DRY_RUN
plan=0
for argument in "$@"; do
  case "$argument" in
    --verbose) export VERBOSE=1 ;;
    --dry-run) export DRY_RUN=1 ;;
    --plan) plan=1 ;;
    --help) printf 'usage: home-switch [--verbose] [--dry-run] [--plan]\n'; exit 0 ;;
    *) printf 'usage: home-switch [--verbose] [--dry-run] [--plan]\n' >&2; exit 2 ;;
  esac
done
if ((plan)); then
  # The generation profile points at the active activation package.
  profile="${XDG_STATE_HOME:-$HOME/.local/state}/nix/profiles/home-manager"
  active=$(readlink -f "$profile" 2>/dev/null || true)
  if [[ $active == "$(readlink -f "$activation_package")" ]]; then
    line='= Home Manager generation unchanged' style=2
  else
    line="~ Home Manager activates a new generation ($activation_package)" style=33
  fi
  if [[ -t 1 && ${TERM:-dumb} != dumb && ! -v NO_COLOR && -z ${CI:-} && -z ${VERBOSE:-} ]]; then
    printf '\033[%sm%s\033[0m\n' "$style" "$line"
  else
    printf '%s\n' "$line"
  fi
  exit 0
fi
# The locked Home Manager activation driver 0 updates its generation profile
# at writeBoundary, after preflight. No second evaluation or target override.
unset HOME_MANAGER_BACKUP_EXT HOME_MANAGER_BACKUP_OVERWRITE SKIP_SANITY_CHECKS
# Home Manager activation requires USER; non-login shells may not set it.
export USER="${USER:-$(id -un)}"
printf '[start] Home Manager activation\n' >&2
exec "$activation_package/activate" --driver-version 0
