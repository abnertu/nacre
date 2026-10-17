# Private implementation. package.nix supplies all paths and declared values.
# The test harness supplies an isolated filesystem and fake native commands.
usage() { printf 'usage: arch-switch [--check | --update | --purge] [--verbose]\n'; }
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
update_system=0
purge=0
verbose=0
for argument in "$@"; do
  case "$argument" in
    --check) check_only=1 ;;
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
if ((check_only && (update_system || purge))); then
  usage >&2
  exit 2
fi

[[ -e $fs_root/etc/arch-release ]] || fail 'arch-switch only supports Arch Linux'
[[ $(native id -u) != 0 ]] || fail 'run arch-switch as the login user, not root'
login_user=$(native id --user --name)
[[ $login_user == "$expected_user" ]] || fail "arch-switch must run as $expected_user, not $login_user"
has_group() { native id -nG "$login_user" | tr ' ' '\n' | grep -Fxq "$1"; }
has_group wheel || fail 'deployment user is not in required administrator group: wheel'

# Check every native dependency before any mutation. Nix supplies text utilities.
required_commands=(id sudo pacman pacman-conf yay install mv rm touch mkdir mktemp
  systemctl sysctl gpasswd modprobe getent groupadd useradd chown chmod)
if ((${manage_sunshine:-1})); then required_commands+=(getcap setcap); fi
if ((${manage_initramfs:-1})); then required_commands+=(mkinitcpio); fi
for command in "${required_commands[@]}"; do
  [[ -x $native_bin/$command ]] || fail "required command is missing: $native_bin/$command"
done

work_dir=$(mktemp -d)
pending_file=''
cleanup() {
  local status=$?
  progress_exit "$status"
  if [[ -n $pending_file ]]; then root rm -f -- "$pending_file"; fi
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

resolve_inventory() {
  local pacman_err="$work_dir/pacman-resolve.err" package
  for package in "${pacman_packages[@]}"; do
    if [[ $package == lib32-* ]]; then
      native pacman-conf --repo multilib Server >/dev/null 2>&1 ||
        fail "declared package $package requires the [multilib] repository in /etc/pacman.conf"
      break
    fi
  done
  if ! native pacman --sync --print --needed -- "${pacman_packages[@]}" 2>"$pacman_err" >/dev/null; then
    progress_suspend
    if [[ -s $pacman_err ]]; then
      if [[ ${progress_interactive:-0} == 1 ]]; then
        printf '\033[1;31mPackage resolution error:\033[0m\n' >&2
      else
        printf 'Package resolution error:\n' >&2
      fi
      cat "$pacman_err" >&2
    fi
    progress_resume
    fail 'Arch package inventory did not resolve; check for package conflicts'
  fi
  if ((${#lizardbyte_package_names[@]})); then
    raw "$curl_bin" --fail --location --show-error --silent --connect-timeout 10 --max-time 60 \
      --output "$work_dir/lizardbyte.db" "$lizardbyte_server/lizardbyte.db"
    raw "$tar_bin" -tf "$work_dir/lizardbyte.db" >"$work_dir/lizardbyte-files"
    for package in "${lizardbyte_package_names[@]}"; do
      grep -Eq "^$package-[^/]+/desc$" "$work_dir/lizardbyte-files" ||
        fail "LizardByte package did not resolve: $package"
    done
  fi
  if ((${#aur_packages[@]})); then
    local yay_err="$work_dir/yay-resolve.err"
    if ! native yay --sync --info -- "${aur_packages[@]}" 2>"$yay_err" >/dev/null; then
      progress_suspend
      if [[ -s $yay_err ]]; then
        if [[ ${progress_interactive:-0} == 1 ]]; then
          printf '\033[1;31mAUR package resolution error:\033[0m\n' >&2
        else
          printf 'AUR package resolution error:\n' >&2
        fi
        cat "$yay_err" >&2
      fi
      progress_resume
      fail 'AUR package inventory did not resolve'
    fi
  fi
}
repo_file="$fs_root/etc/pacman.d/nix-config-lizardbyte.conf"
repo_include='Include = /etc/pacman.d/nix-config-lizardbyte.conf'
lizardbyte_server=""
if ((${#lizardbyte_package_names[@]})); then
  lizardbyte_server=$(native pacman-conf --config "$files/pacman-lizardbyte.conf" --repo lizardbyte Server)
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
exec {lock_fd}>"$runtime_dir/nix-config-arch.lock"
"$flock_bin" -n "$lock_fd" || fail 'another arch-switch is running' 75

if ((purge)); then
  progress_start 'Purge managed Arch state' 1
  [[ $update_system == 0 ]] || fail '--purge cannot be combined with --update' 2
  root_state="$fs_root/var/lib/nix-config/arch"
  native sudo -v
  for service in "${system_units[@]}"; do
    native systemctl is-enabled --quiet "$service" && root systemctl disable --now "$service" || true
  done
  # Drop the Include before its target: pacman cannot load a missing include.
  if [[ -e $fs_root/etc/pacman.conf ]] && grep -Fxq "$repo_include" "$fs_root/etc/pacman.conf"; then
    grep -Fxv "$repo_include" "$fs_root/etc/pacman.conf" >"$work_dir/pacman.conf" || true
    root install -m0644 -o0 -g0 -- "$work_dir/pacman.conf" "$fs_root/etc/pacman.conf"
  fi
  for path in \
    "$fs_root/etc/NetworkManager/conf.d/main.conf" \
    "$fs_root/etc/NetworkManager/conf.d/99-tailscale.conf" \
    "$fs_root/etc/modules-load.d/nix-config-podman.conf" \
    "$fs_root/etc/sysctl.d/99-nix-config.conf" \
    "$fs_root/etc/systemd/system/getty@tty1.service.d/override.conf" \
    "$fs_root/etc/pwrstatd.conf" \
    "$fs_root/etc/pacman.d/nix-config-lizardbyte.conf"; do
    [[ ! -e $path ]] || root rm -f -- "$path"
  done
  if [[ -e $fs_root/etc/nix/nix.conf ]]; then
    sed '/^# BEGIN nix-config settings$/,/^# END nix-config settings$/d' "$fs_root/etc/nix/nix.conf" >"$work_dir/nix.conf"
    root install -m0644 -o0 -g0 -- "$work_dir/nix.conf" "$fs_root/etc/nix/nix.conf"
    if native systemctl is-active --quiet nix-daemon.service; then
      root systemctl restart nix-daemon.service
    fi
  fi
  [[ ! -e $root_state ]] || root rm -rf -- "$root_state"
  personal_units_changed=0
  service="personal-agent.service"
  unit="$fs_root/etc/systemd/system/$service"
  if [[ -e $unit ]]; then
    native systemctl is-enabled --quiet "$service" &&
      root systemctl disable --now "$service" || true
    root rm -f -- "$unit"
    personal_units_changed=1
  fi
  ((personal_units_changed == 0)) || root systemctl daemon-reload
  progress_suspend
  printf 'Arch deployment state purged; package and user data were preserved.\n'
  progress_resume
  progress_update 1 1
  progress_finish 'done'
  exit 0
fi

total_steps=5
if ((update_system)); then total_steps=6; fi
current_step=1

progress_start "[$current_step/$total_steps] Validate Arch host, packages, and kernel"
current_step=$((current_step + 1))

missing_packages=()
for package in "${pacman_packages[@]}" "${lizardbyte_package_names[@]}" "${aur_packages[@]}"; do
  native pacman --query -- "$package" >/dev/null 2>&1 || missing_packages+=("$package")
done
if ((!update_system && ${#missing_packages[@]})); then
  progress_suspend
  printf 'declared Arch packages are missing; rerun with --update to install them safely:\n' >&2
  printf '  %s\n' "${missing_packages[@]}" >&2
  progress_resume
  exit 3
fi
running_kernel=$(uname -r)
check_kernel() {
  [[ -d $fs_root/usr/lib/modules/$running_kernel ]] ||
    fail "kernel modules do not match running kernel $running_kernel; reboot, then rerun the deployment" 75
}
check_kernel
progress_finish 'done'
if ((${#lizardbyte_package_names[@]})) && ! grep -Fxq "$repo_include" "$fs_root/etc/pacman.conf" &&
  native pacman-conf --repo lizardbyte Server >/dev/null 2>&1; then
  fail 'an unmanaged [lizardbyte] repository already exists in pacman.conf'
fi
adapter_args() {
  local manifest=$1 phase=$2
  local args=("$manifest" "$phase")
  if ((verbose)); then args+=(--verbose); fi
  printf '%s\0' "${args[@]}"
}
system_settings() {
  local args=()
  mapfile -d '' -t args < <(adapter_args "$system_manifest" "$1")
  native sudo "$system_python" "$system_adapter" "${args[@]}"
}
ai_settings() {
  local args=()
  mapfile -d '' -t args < <(adapter_args "$ai_manifest" "$1")
  native sudo "$ai_python" "$ai_adapter" "${args[@]}"
}
personal_agent_settings() {
  local args=()
  mapfile -d '' -t args < <(adapter_args "$personal_agent_manifest" "$1")
  native sudo "$personal_agent_python" "$personal_agent_adapter" "${args[@]}"
}
# Read-only ownership preflight precedes package/configuration writes. A second
# pass after updates checks newly installed native tools and configuration.
progress_start "[$current_step/$total_steps] Preflight core and optional modules"
current_step=$((current_step + 1))
system_settings preflight
ai_skipped=0
if ai_settings preflight; then
  :
else
  ai_status=$?
  if ((ai_status == 20)); then
    ai_skipped=1
    optional_skip 'ai' "llama.cpp build/model is not prepared; run 'just prepare-ai'"
  else
    exit "$ai_status"
  fi
fi
personal_agent_skipped=0
if ((ai_skipped)); then
  personal_agent_skipped=1
  optional_skip 'personal-agent' 'local inference is not ready'
elif personal_agent_settings preflight; then
  :
else
  personal_agent_status=$?
  if ((personal_agent_status == 20)); then
    personal_agent_skipped=1
    optional_skip 'personal-agent' 'runtime configuration is not prepared'
  else
    exit "$personal_agent_status"
  fi
fi
progress_finish 'done'
if ((update_system)); then
  progress_start "[$current_step/$total_steps] Resolve and update native packages"
  current_step=$((current_step + 1))
  resolve_inventory
fi

root_state="$fs_root/var/lib/nix-config/arch"
native sudo -v
root install -d -m0755 -o0 -g0 "$root_state"
changed_files=0
actions=0

# Mark pending actions BEFORE replacing a file. A failed action (or interrupted
# write) remains pending across invocations even when the file already matches.
ensure_file() {
  local source=$1 target=$2 action=${3:-}
  [[ ! -L $target ]] || fail "managed file is a symlink: $target"
  if [[ -f $target ]] && cmp -s "$source" "$target" &&
    [[ $(stat -c '%a:%u:%g' "$target") == "$managed_identity" ]]; then
    return 0
  fi
  if [[ -n $action ]]; then root touch "$root_state/$action.pending"; fi
  root mkdir -p -- "$(dirname "$target")"
  pending_file=$(root mktemp "$(dirname "$target")/.nix-config.XXXXXXXX")
  root install -m0644 -o0 -g0 -- "$source" "$pending_file"
  root mv -fT -- "$pending_file" "$target"
  pending_file=''
  changed_files=$((changed_files + 1))
  progress_suspend
  printf 'updated %s\n' "${target#"$fs_root"}"
  progress_resume
}
if ((${#lizardbyte_package_names[@]})); then
  ensure_file "$files/pacman-lizardbyte.conf" "$repo_file"
  if ! grep -Fxq "$repo_include" "$fs_root/etc/pacman.conf"; then
    {
      cat "$fs_root/etc/pacman.conf"
      printf '\n%s\n' "$repo_include"
    } >"$work_dir/pacman.conf"
    ensure_file "$work_dir/pacman.conf" "$fs_root/etc/pacman.conf"
  fi
  [[ $(native pacman-conf --repo lizardbyte Server) == "$lizardbyte_server" ]] ||
    fail 'managed [lizardbyte] repository did not load as expected'
fi
if ((update_system)); then
  root pacman --sync --refresh --sysupgrade --needed --noconfirm -- \
    "${pacman_packages[@]}" "${lizardbyte_packages[@]}"
  check_kernel
  if ((${#aur_packages[@]})); then native yay --sync --needed --noconfirm -- "${aur_packages[@]}"; fi
  progress_finish 'done'
fi

progress_start "[$current_step/$total_steps] Converge core files and services"
current_step=$((current_step + 1))
system_settings converge

if ((${manage_network:-1})); then
  ensure_file "$files/NetworkManager-main.conf" "$fs_root/etc/NetworkManager/conf.d/main.conf" network
  if ((${manage_tailscale:-1})); then
    ensure_file "$files/NetworkManager-tailscale.conf" "$fs_root/etc/NetworkManager/conf.d/99-tailscale.conf" network
  fi
fi
ensure_file "$files/container-network-modules.conf" "$fs_root/etc/modules-load.d/nix-config-podman.conf"
ensure_file "$files/sysctl.conf" "$fs_root/etc/sysctl.d/99-nix-config.conf"
if ((${manage_powerpanel:-0})); then
  ensure_file "$powerpanel_conf" "$fs_root/etc/pwrstatd.conf" pwrstatd
fi
if ((${manage_desktop:-1})); then
  sed "s/@USER@/$login_user/g" "$files/tty1-autologin.conf" >"$work_dir/autologin.conf"
  ensure_file "$work_dir/autologin.conf" "$fs_root/etc/systemd/system/getty@tty1.service.d/override.conf" units
fi

if ((${manage_initramfs:-1})); then
  # Own only this marked addition, preserving administrator MODULES and HOOKS.
  awk '
  /^# BEGIN nix-config modules$/ { if (managed) exit 1; managed = 1; next }
  /^# END nix-config modules$/ { if (!managed) exit 1; managed = 0; next }
  !managed { print }
  END { if (managed) exit 1 }
' "$fs_root/etc/mkinitcpio.conf" >"$work_dir/mkinitcpio.conf"
  {
    printf '# BEGIN nix-config modules\nMODULES+=('
    printf ' %s' "${initramfs_modules[@]}"
    printf ' )\n# END nix-config modules\n'
  } >>"$work_dir/mkinitcpio.conf"
  ensure_file "$work_dir/mkinitcpio.conf" "$fs_root/etc/mkinitcpio.conf" initramfs
  for image in "${initramfs_images[@]}"; do
    if [[ ! -s $fs_root$image ]]; then root touch "$root_state/initramfs.pending"; fi
  done
  if [[ -e $root_state/initramfs.pending ]]; then
    root mkinitcpio -P
    for image in "${initramfs_images[@]}"; do
      [[ -s $fs_root$image ]] || fail "initramfs was not generated: $image"
    done
    root rm -- "$root_state/initramfs.pending"
    actions=$((actions + 1))
  fi
fi
if [[ -f $fs_root/etc/nix/nix.conf ]]; then
  awk '
  /^# BEGIN nix-config settings$/ { if (managed) exit 1; managed = 1; next }
  /^# END nix-config settings$/ { if (!managed) exit 1; managed = 0; next }
  !managed { print }
  END { if (managed) exit 1 }
' "$fs_root/etc/nix/nix.conf" >"$work_dir/nix.conf"
else
  : >"$work_dir/nix.conf"
fi
{
  printf '# BEGIN nix-config settings\ntrusted-users = root @wheel %s\n# END nix-config settings\n' "$login_user"
} >>"$work_dir/nix.conf"
ensure_file "$work_dir/nix.conf" "$fs_root/etc/nix/nix.conf" nix-daemon
groups_changed=0
for group in "${required_groups[@]}"; do
  if ! has_group "$group"; then
    root gpasswd --add "$login_user" "$group"
    groups_changed=1
  fi
done

if (( ${manage_desktop:-1} )) && [[ -e $root_state/units.pending ]]; then
  root systemctl daemon-reload
  root rm -- "$root_state/units.pending"
  actions=$((actions + 1))
fi
for service in "${system_units[@]}"; do
  if ! native systemctl is-enabled --quiet "$service"; then
    root systemctl enable "$service"
    actions=$((actions + 1))
  fi
  if ! native systemctl is-active --quiet "$service"; then
    root systemctl start "$service"
    native systemctl is-active --quiet "$service" ||
      fail "required system unit $service did not become active"
    actions=$((actions + 1))
  fi
done
progress_finish 'done'
progress_start "[$current_step/$total_steps] Converge optional modules"
current_step=$((current_step + 1))
if ((!ai_skipped)); then
  if ai_settings converge; then
    :
  else
    ai_status=$?
    if ((ai_status == 20)); then
      printf '%s\n' 'AI preparation changed after preflight; deployment stopped' >&2
      exit 1
    fi
    exit "$ai_status"
  fi
fi
if ((!personal_agent_skipped)); then
  if personal_agent_settings converge; then
    :
  else
    personal_agent_status=$?
    if ((personal_agent_status == 20)); then
      printf '%s\n' 'Personal Agent configuration changed after preflight; deployment stopped' >&2
      exit 1
    fi
    exit "$personal_agent_status"
  fi
fi
progress_finish 'done'
progress_start "[$current_step/$total_steps] Finish runtime convergence"
current_step=$((current_step + 1))
if ((${manage_network:-1})) && [[ -e $root_state/network.pending ]]; then
  root systemctl restart NetworkManager.service
  root rm -- "$root_state/network.pending"
  actions=$((actions + 1))
fi
if [[ -e $root_state/nix-daemon.pending ]]; then
  root systemctl restart nix-daemon.service
  root rm -- "$root_state/nix-daemon.pending"
  actions=$((actions + 1))
fi
if [[ -e $root_state/pwrstatd.pending ]]; then
  if native systemctl is-active --quiet pwrstatd.service; then
    root systemctl restart pwrstatd.service
  fi
  root rm -- "$root_state/pwrstatd.pending"
  actions=$((actions + 1))
fi
# Compare runtime values too: unchanged files must not conceal runtime drift.
while IFS= read -r module; do
  [[ -n $module && $module != \#* ]] || continue
  if [[ ! -d $fs_root/sys/module/$module ]]; then
    root modprobe "$module"
    actions=$((actions + 1))
  fi
done <"$files/container-network-modules.conf"
while IFS='=' read -r key desired; do
  key=$(printf '%s' "$key" | xargs)
  [[ -n $key && $key != \#* ]] || continue
  desired=$(printf '%s' "$desired" | xargs)
  actual=$(native sysctl -n "$key")
  if [[ $actual != "$desired" ]]; then
    root sysctl -w "$key=$desired"
    actions=$((actions + 1))
  fi
done <"$files/sysctl.conf"
for service in "${user_services[@]}"; do
  if ! native systemctl --user is-enabled --quiet "$service"; then
    native systemctl --user enable "$service"
    actions=$((actions + 1))
  fi
done
if ((${manage_sunshine:-1})); then
  sunshine=$(readlink -f "$native_bin/sunshine")
  [[ -f $sunshine ]] || fail 'Sunshine executable is missing'
  if [[ $(native getcap "$sunshine") != "$sunshine cap_sys_admin=p" ]]; then
    root setcap cap_sys_admin+p "$sunshine"
    actions=$((actions + 1))
  fi
fi
progress_finish 'done'
printf 'Arch converged: %s files updated, %s runtime actions.\n' "$changed_files" "$actions"
if ((groups_changed)); then printf 'Group membership changed; log out and back in.\n'; fi
