arch_switch_args=()
home_switch_args=()
update_seen=0
purge_seen=0
plan_seen=0
verbose_seen=0
forget_seen=0
usage() { printf 'usage: %s [--plan | --update | --purge | --forget RECORD] [--verbose]\n' "$deployment_name"; }
while (($#)); do
  argument=$1
  shift
  case "$argument" in
    --forget)
      ((update_seen == 0 && $# > 0)) && [[ $1 != --* ]] || {
        usage >&2
        exit 2
      }
      update_seen=1
      forget_seen=1
      arch_switch_args+=(--forget "$1")
      shift
      ;;
    --update)
      ((update_seen == 0)) || {
        usage >&2
        exit 2
      }
      update_seen=1
      arch_switch_args+=(--update)
      ;;
    --purge)
      ((update_seen == 0)) || {
        usage >&2
        exit 2
      }
      update_seen=1
      purge_seen=1
      arch_switch_args+=(--purge)
      ;;
    --plan)
      ((update_seen == 0)) || {
        usage >&2
        exit 2
      }
      update_seen=1
      plan_seen=1
      arch_switch_args+=(--plan)
      home_switch_args+=(--plan)
      ;;
    --verbose)
      ((verbose_seen == 0)) || {
        usage >&2
        exit 2
      }
      verbose_seen=1
      arch_switch_args+=(--verbose)
      home_switch_args+=(--verbose)
      ;;
    --help)
      if (($# == 1)); then
        usage
        exit 0
      fi
      usage >&2
      exit 2
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done
if ((plan_seen)); then
  printf '\n==> Plan: Arch changes <==\n\n' >&2
  "$arch_switch" "${arch_switch_args[@]}"
  printf '\n==> Plan: Home Manager <==\n\n' >&2
  exec "$home_switch" "${home_switch_args[@]}"
fi
printf '\n==> Phase 1/2: Arch System Convergence <==\n\n' >&2
"$arch_switch" "${arch_switch_args[@]}"
if ((purge_seen || forget_seen)); then
  exit 0
fi
printf '\n==> Phase 2/2: Home Manager Activation <==\n\n' >&2
exec "$home_switch" "${home_switch_args[@]}"
