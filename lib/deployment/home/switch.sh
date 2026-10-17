unset DRY_RUN
for argument in "$@"; do
  case "$argument" in
    --verbose) export VERBOSE=1 ;;
    --dry-run) export DRY_RUN=1 ;;
    --help) printf 'usage: home-switch [--verbose] [--dry-run]\n'; exit 0 ;;
    *) printf 'usage: home-switch [--verbose] [--dry-run]\n' >&2; exit 2 ;;
  esac
done
# The locked Home Manager activation driver 0 updates its generation profile
# at writeBoundary, after preflight. No second evaluation or target override.
unset HOME_MANAGER_BACKUP_EXT HOME_MANAGER_BACKUP_OVERWRITE SKIP_SANITY_CHECKS
# Home Manager activation requires USER; non-login shells may not set it.
export USER="${USER:-$(id -un)}"
printf '[start] Home Manager activation\n' >&2
exec "$activation_package/activate" --driver-version 0
