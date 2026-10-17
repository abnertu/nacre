# Private implementation. package.nix supplies all paths and declared values.
# The test harness supplies an isolated filesystem and fake native commands.
# Package operations run here because yay must run as the login user; the
# privileged Python adapters own every file, unit and runtime change.
usage() { printf 'usage: arch-switch [--check | --plan | --update | --purge] [--verbose]\n'; }
native() {
  local status
  progress_suspend
  status=0
  "$native_bin/$1" "${@:2}" || status=$?
  progress_resume
  return "$status"
}
root() {
  native sudo "$native_bin/$1" "${@:2}"
}
fail() {
  progress_suspend
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
}
optional_skip() {
  progress_suspend
  if [[ ${progress_interactive:-0} == 1 ]]; then
    printf '\033[1;33mSKIP optional module %s: %s\033[0m\n' "$1" "$2" >&2
  else
    printf 'SKIP optional module %s: %s\n' "$1" "$2" >&2
  fi
  progress_resume
}

check_only=0
plan_only=0
update_system=0
purge=0
verbose=0
for argument in "$@"; do
  case "$argument" in
    --check) check_only=1 ;;
    --plan) plan_only=1 ;;
    --update) update_system=1 ;;
    --purge) purge=1 ;;
    --verbose) verbose=1 ;;
    --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done
progress_init arch "$verbose"
arch_exit() {
  local status=$?
  progress_exit "$status"
  return "$status"
}
trap arch_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ((check_only + plan_only + update_system + purge > 1)); then
  usage >&2
  exit 2
fi

[[ -e $fs_root/etc/arch-release ]] || fail 'arch-switch only supports Arch Linux'
[[ $(native id -u) != 0 ]] || fail 'run arch-switch as the login user, not root'
login_user=$(native id --user --name)
[[ $login_user == "$expected_user" ]] || fail "arch-switch must run as $expected_user, not $login_user"
native id -nG "$login_user" | tr ' ' '\n' | grep -Fxq wheel ||
  fail 'deployment user is not in required administrator group: wheel'

# The adapters check their own commands; these are the orchestration's.
for command in id sudo pacman pacman-conf yay systemctl; do
  [[ -x $native_bin/$command ]] || fail "required command is missing: $native_bin/$command"
done

work_dir=$(mktemp -d)
cleanup() {
  local status=$?
  progress_exit "$status"
  rm -rf -- "$work_dir"
  return "$status"
}
trap cleanup EXIT

raw() {
  local status=0
  progress_suspend
  "$@" || status=$?
  progress_resume
  return "$status"
}
report_failure() {
  progress_suspend
  if [[ -s $2 ]]; then
    if [[ ${progress_interactive:-0} == 1 ]]; then
      printf '\033[1;31m%s:\033[0m\n' "$1" >&2
    else
      printf '%s:\n' "$1" >&2
    fi
    cat "$2" >&2
  fi
  progress_resume
}

resolve_inventory() {
  local package
  for package in "${pacman_packages[@]}"; do
    if [[ $package == lib32-* ]]; then
      native pacman-conf --repo multilib Server >/dev/null 2>&1 ||
        fail "declared package $package requires the [multilib] repository in /etc/pacman.conf"
      break
    fi
  done
  if ! native pacman --sync --print --needed -- "${pacman_packages[@]}" \
    2>"$work_dir/pacman-resolve.err" >/dev/null; then
    report_failure 'Package resolution error' "$work_dir/pacman-resolve.err"
    fail 'Arch package inventory did not resolve; check for package conflicts'
  fi
  if ((${#lizardbyte_package_names[@]})); then
    local server
    server=$(native pacman-conf --config "$lizardbyte_conf" --repo lizardbyte Server)
    raw "$curl_bin" --fail --location --show-error --silent --connect-timeout 10 --max-time 60 \
      --output "$work_dir/lizardbyte.db" "$server/lizardbyte.db"
    raw "$tar_bin" -tf "$work_dir/lizardbyte.db" >"$work_dir/lizardbyte-files"
    for package in "${lizardbyte_package_names[@]}"; do
      grep -Eq "^$package-[^/]+/desc$" "$work_dir/lizardbyte-files" ||
        fail "LizardByte package did not resolve: $package"
    done
  fi
  if ((${#aur_packages[@]})) &&
    ! native yay --sync --info -- "${aur_packages[@]}" 2>"$work_dir/yay-resolve.err" >/dev/null; then
    report_failure 'AUR package resolution error' "$work_dir/yay-resolve.err"
    fail 'AUR package inventory did not resolve'
  fi
}
adapter() {
  local args=("$1" "$2" "$3")
  if ((verbose)); then args+=(--verbose); fi
  if [[ $3 == plan ]] && ((plan_color)); then args+=(--color); fi
  native sudo "$adapter_python" "${args[@]}"
}
core() { adapter "$core_adapter" "$core_manifest" "$1"; }
running_kernel=$(uname -r)
check_kernel() {
  [[ -d $fs_root/usr/lib/modules/$running_kernel ]] ||
    fail "kernel modules do not match running kernel $running_kernel; reboot, then rerun the deployment" 75
}
# An optional adapter exits 20 only while its preparation has never completed.
optional_preflight() {
  local name=$1 reason=$2 status=0
  adapter "$3" "$4" preflight || status=$?
  if ((status == 20)); then
    optional_skip "$name" "$reason"
    return 1
  fi
  ((status == 0)) || exit "$status"
}
optional_converge() {
  local status=0
  adapter "$2" "$3" converge || status=$?
  if ((status == 20)); then
    printf '%s changed after preflight; deployment stopped\n' "$1" >&2
    exit 1
  fi
  ((status == 0)) || exit "$status"
}

missing_packages=()
find_missing_packages() {
  local package
  for package in "${pacman_packages[@]}" "${lizardbyte_package_names[@]}" "${aur_packages[@]}"; do
    native pacman --query -- "$package" >/dev/null 2>&1 || missing_packages+=("$package")
  done
}

# Plan lines share the core adapter's markers: = unchanged, ~ change,
# + addition, ! conflict. Color follows the progress display's terminal rules.
plan_color=0
if ((${progress_interactive:-0})) && [[ -t 1 ]]; then plan_color=1; fi
plan_line() {
  local style
  case "$1" in
    '=') style=2 ;;
    '~') style=33 ;;
    '+') style=32 ;;
    '!') style='1;31' ;;
    *) style='1;33' ;;
  esac
  progress_suspend
  if ((plan_color)); then
    printf '\033[%sm%s %s\033[0m\n' "$style" "$1" "$2"
  else
    printf '%s %s\n' "$1" "$2"
  fi
  progress_resume
}

if ((plan_only)); then
  progress_start 'Plan Arch changes' 1
  find_missing_packages
  for package in "${missing_packages[@]}"; do
    plan_line '+' "package $package (missing; installed by update)"
  done
  if [[ -x $native_bin/checkupdates ]]; then
    upgrades=0
    if output=$(native checkupdates 2>/dev/null); then
      upgrades=$(printf '%s\n' "$output" | grep -c .)
    fi
    if ((upgrades)); then plan_line '~' "$upgrades repository package upgrades available (installed by update)"; fi
  fi
  if [[ ! -d $fs_root/usr/lib/modules/$running_kernel ]]; then
    plan_line '!' "kernel modules do not match running kernel $running_kernel; reboot first"
  fi
  core plan
  adapter "$system_adapter" "$system_manifest" preflight
  plan_line '=' 'system settings preflight passed (their changes are not previewed)'
  if optional_preflight ai "llama.cpp build/model is not prepared; run 'just prepare-ai'" \
    "$ai_adapter" "$ai_manifest"; then
    plan_line '=' 'ai ready'
    if optional_preflight personal-agent 'runtime configuration is not prepared' \
      "$personal_agent_adapter" "$personal_agent_manifest"; then
      plan_line '=' 'personal-agent ready'
    fi
  else
    optional_skip personal-agent 'local inference is not ready'
  fi
  for service in "${user_services[@]}"; do
    if ! native systemctl --user is-enabled --quiet "$service"; then
      plan_line '~' "enable user service $service"
    fi
  done
  progress_update 1 1
  progress_finish 'done'
  exit 0
fi

if ((check_only)); then
  progress_start 'Check package inventories' 1
  resolve_inventory
  progress_suspend
  printf 'Arch, LizardByte, and AUR package inventories resolve\n'
  progress_resume
  progress_update 1 1
  progress_finish 'done'
  exit 0
fi

# Only the selected login user can deploy. Its private runtime directory also
# serializes update and routine activation; the lock inode is never removed.
runtime_dir="$fs_root/run/user/$(native id -u)"
[[ -d $runtime_dir && ! -L $runtime_dir ]] || fail 'login runtime directory is unavailable'
exec {lock_fd}>"$runtime_dir/nacre-arch.lock"
"$flock_bin" -n "$lock_fd" || fail 'another arch-switch is running' 75


if ((purge)); then
  progress_start 'Purge managed Arch state' 1
  native sudo -v
  # Optional services first, then system drop-ins; core removes pending state.
  adapter "$ai_adapter" "$ai_manifest" purge
  adapter "$system_adapter" "$system_manifest" purge
  core purge
  progress_update 1 1
  progress_finish 'done'
  exit 0
fi

total_steps=5
if ((update_system)); then total_steps=6; fi
current_step=1
next_step() {
  progress_start "[$current_step/$total_steps] $1"
  current_step=$((current_step + 1))
}

next_step 'Validate Arch host, packages, and kernel'
find_missing_packages
if ((!update_system && ${#missing_packages[@]})); then
  progress_suspend
  printf 'declared Arch packages are missing; rerun with --update to install them safely:\n' >&2
  printf '  %s\n' "${missing_packages[@]}" >&2
  progress_resume
  exit 3
fi
check_kernel
progress_finish 'done'

# Read-only ownership preflight precedes package and configuration writes.
next_step 'Preflight core and optional modules'
core preflight
adapter "$system_adapter" "$system_manifest" preflight
ai_ready=0 personal_agent_ready=0
if optional_preflight ai "llama.cpp build/model is not prepared; run 'just prepare-ai'" \
  "$ai_adapter" "$ai_manifest"; then
  ai_ready=1
fi
if ((!ai_ready)); then
  optional_skip personal-agent 'local inference is not ready'
elif optional_preflight personal-agent 'runtime configuration is not prepared' \
  "$personal_agent_adapter" "$personal_agent_manifest"; then
  personal_agent_ready=1
fi
progress_finish 'done'

native sudo -v
if ((update_system)); then
  next_step 'Resolve and update native packages'
  resolve_inventory
  core repositories
  root pacman --sync --refresh --sysupgrade --needed --noconfirm -- \
    "${pacman_packages[@]}" "${lizardbyte_packages[@]}"
  check_kernel
  if ((${#aur_packages[@]})); then native yay --sync --needed --noconfirm -- "${aur_packages[@]}"; fi
  progress_finish 'done'
else
  core repositories
fi

next_step 'Converge core files and services'
adapter "$system_adapter" "$system_manifest" converge
core converge
progress_finish 'done'

next_step 'Converge optional modules'
if ((ai_ready)); then optional_converge 'AI preparation' "$ai_adapter" "$ai_manifest"; fi
if ((personal_agent_ready)); then
  optional_converge 'Personal Agent configuration' "$personal_agent_adapter" "$personal_agent_manifest"
fi
progress_finish 'done'

next_step 'Finish runtime convergence'
core finish
# User units belong to the login user's manager, so this stays unprivileged.
user_actions=0
for service in "${user_services[@]}"; do
  if ! native systemctl --user is-enabled --quiet "$service"; then
    native systemctl --user enable "$service"
    user_actions=$((user_actions + 1))
  fi
done
printf 'User services converged: 0 files updated, %s runtime actions.\n' "$user_actions"
progress_finish 'done'
