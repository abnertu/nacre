#!/usr/bin/env bash
# Deploy the container-test configuration into a rootless systemd Arch
# container: bootstrap, update, routine, quiet repeat, purge, store integrity.
# Package caches persist in podman volumes so later runs skip most downloads.
set -euo pipefail

usage() { printf 'usage: container-test.sh [--keep]\n'; }
keep=0
for argument in "$@"; do
  case "$argument" in
    --keep) keep=1 ;;
    --help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readonly name=nix-config-container-test
readonly image=docker.io/archlinux/archlinux:latest
work=$(mktemp -d)
cleanup() {
  local status=$?
  rm -rf -- "$work"
  if ((keep)); then
    printf 'kept container %s\n' "$name" >&2
  else
    podman rm -f "$name" >/dev/null 2>&1 || true
  fi
  return "$status"
}
trap cleanup EXIT

current_step='' last_log=''
step() {
  current_step=$1
  printf '\n==> %s\n' "$1"
}
# On GitHub Actions, also raise an error annotation with the failing log's
# tail: annotations are readable without downloading the job log.
annotate() {
  [[ ${GITHUB_ACTIONS:-} == true && -z ${annotated:-} ]] || return 0
  annotated=1
  local text="$1"
  if [[ -n $last_log && -f $work/$last_log ]]; then
    text+=$'\n'"$(tail -n 40 "$work/$last_log" | sed 's/\x1b\[[0-9;]*m//g')"
  fi
  text=${text//'%'/'%25'}
  text=${text//$'\r'/'%0D'}
  text=${text//$'\n'/'%0A'}
  printf '::error title=container-test::%s\n' "$text"
}
fail() {
  printf 'container-test: %s\n' "$1" >&2
  annotate "$1"
  exit 1
}
trap 'annotate "command failed (exit $?) at line $LINENO during: $current_step"' ERR

step 'Build the container deployment'
deployment=$(nix build --no-link --print-out-paths "$source_root#container-deployment")
# shellcheck disable=SC2016 # the single-quoted text is a Nix expression
read -r user home <<<"$(nix eval --raw "$source_root#lib.container" \
  --apply 'c: "${c.username} ${c.homeDirectory}"')"
binary=$(find "$deployment/bin" -mindepth 1 -maxdepth 1 -printf '%f\n' | head -n1)

step 'Start the systemd container'
podman rm -f "$name" >/dev/null 2>&1 || true
podman run -d --name "$name" --hostname arch --systemd=always --privileged \
  -v "/usr/lib/modules/$(uname -r):/usr/lib/modules/$(uname -r):ro" \
  -v nix-config-container-pacman:/var/cache/pacman/pkg \
  -v nix-config-container-yay:/var/cache/nix-config-yay \
  "$image" /usr/lib/systemd/systemd >/dev/null
for _ in $(seq 60); do
  state=$(podman exec "$name" systemctl is-system-running 2>/dev/null || true)
  [[ $state == running || $state == degraded ]] && break
  sleep 1
done
[[ $state == running || $state == degraded ]] || fail "systemd did not start: $state"

step 'Prepare the image and the deployment user'
if [[ -r /etc/pacman.d/mirrorlist ]]; then
  podman cp /etc/pacman.d/mirrorlist "$name:/etc/pacman.d/mirrorlist"
fi
# The image strips locale sources and documentation through NoExtract.
podman exec -i "$name" bash -euo pipefail -s "$user" "$home" <<'EOF'
user=$1 home=$2
sed -i '/^NoExtract/d' /etc/pacman.conf
pacman -Syu --noconfirm --needed sudo >/dev/null
pacman -S --noconfirm glibc >/dev/null # reinstall to extract the locale sources
useradd -m -d "$home" -u 1000 -G wheel "$user"
printf '%%wheel ALL=(ALL:ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/wheel
chown "$user:" /var/cache/nix-config-yay
install -d -o "$user" -g "$user" "$home/.cache"
ln -s /var/cache/nix-config-yay "$home/.cache/yay"
loginctl enable-linger "$user"
EOF
for _ in $(seq 30); do
  podman exec "$name" test -d /run/user/1000 && break
  sleep 1
done

as_user() {
  podman exec -u "$user" -w "$home" -e XDG_RUNTIME_DIR=/run/user/1000 -e NO_COLOR=1 \
    "$name" "$@"
}
deploy() {
  local log=$1
  shift
  local status=0
  as_user "$deployment/bin/$binary" "$@" >"$work/$log" 2>&1 || status=$?
  return "$status"
}
show() {
  last_log=$1
  tail -n 40 "$work/$1" >&2
}

step 'Bootstrap with the checked-in script'
podman cp "$source_root/scripts/bootstrap.sh" "$name:/tmp/bootstrap.sh"
as_user bash /tmp/bootstrap.sh >"$work/bootstrap.log" 2>&1 || { show bootstrap.log; fail 'bootstrap failed'; }

step 'Import the deployment closure'
mapfile -t closure < <(nix-store --query --requisites "$deployment")
nix-store --export "${closure[@]}" | podman exec -i "$name" nix-store --import >/dev/null

step 'Routine deployment refuses missing packages'
status=0
deploy missing.log || status=$?
((status == 3)) || { show missing.log; fail "expected exit 3, got $status"; }

step 'Update installs packages and converges'
deploy update.log --update || { show update.log; fail 'update failed'; }

step 'Repeat deployment changes nothing'
deploy repeat.log || { show repeat.log; fail 'repeat deployment failed'; }
if grep -E 'converged: ' "$work/repeat.log" | grep -Ev 'converged: 0 files updated, 0 runtime actions' ||
  grep -E '^updated /' "$work/repeat.log"; then
  fail 'repeat deployment was not quiet'
fi

step 'Plan agrees that nothing is left to change'
deploy plan.log --plan || { show plan.log; fail 'plan failed'; }
# Upstream may publish packages between update and plan: available upgrades
# are information, not deployment drift.
if ! grep -Fxq 'Core plan: 0 files to update, 0 runtime actions.' "$work/plan.log" ||
  grep -E '^[~+!] ' "$work/plan.log" | grep -v 'repository package upgrades available'; then
  last_log=plan.log
  fail 'plan reported changes after a converged deployment'
fi

step 'Purge withdraws managed state and keeps pacman usable'
deploy purge.log --purge || { show purge.log; fail 'purge failed'; }
podman exec "$name" pacman -Q >/dev/null || fail 'pacman is unusable after purge'
if podman exec "$name" test -e /var/lib/nix-config/arch; then fail 'purge kept pending state'; fi

step 'Store paths are unmodified'
podman exec "$name" nix-store --verify --check-contents >"$work/verify.log" 2>&1 ||
  { show verify.log; fail 'store verification failed'; }

printf '\ncontainer-test: passed\n'
