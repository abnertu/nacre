#!/usr/bin/env bash
# Install or upgrade Nacre on Arch Linux. Run the newest release's copy:
#   bash <(curl -fsSL https://github.com/abnertu/nacre/releases/latest/download/install.sh)
# Prepares the native prerequisites only when one is missing, then runs the
# newest release's nacre: `upgrade self` for an existing checkout, else
# `install` (with `--repo` when NACRE_REPO is set).

set -euo pipefail

usage() {
  cat <<'EOF'
usage: install.sh [--help]

Install or upgrade Nacre on Arch Linux:
  1. When a prerequisite is missing: enable [multilib] and install
     base-devel, git, nix and just with pacman -Syu.
  2. Configure /etc/nix/nix.conf, start nix-daemon.service, add the login
     user to wheel, and install yay when it is absent.
  3. Find the checkout: NACRE_DIR, else $XDG_CONFIG_HOME/nacre, else
     $XDG_CONFIG_HOME/nix (XDG_CONFIG_HOME defaults to ~/.config).
  4. With a flake there: run the newest release's `nacre upgrade self`.
     Without one: run `nacre install`, or `nacre install --repo $NACRE_REPO`.

Environment:
  NACRE_REPO  machine repository to clone into a new checkout
  NACRE_DIR   checkout to use
  NACRE_YES   1: run without questions, also without a terminal
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

if [[ ! -f /etc/arch-release ]]; then
  printf 'error: install.sh only supports Arch Linux\n' >&2
  exit 1
fi

if ((EUID == 0)); then
  printf 'error: run install.sh as your regular login user with sudo privileges, not root\n' >&2
  exit 1
fi

login_user=$(id --user --name)
printf '==> Nacre for user: %s\n' "$login_user"

# 1. Native base dependencies. Declared lib32 packages require [multilib].
packages=(base-devel git nix just)
multilib=1
pacman-conf --repo multilib Server >/dev/null 2>&1 || multilib=0
missing=$(pacman -T "${packages[@]}" || true)
if ((!multilib)) || [[ -n $missing ]]; then
  printf '==> Enabling [multilib] and installing native packages (%s)...\n' "${packages[*]}"
  if ((!multilib)); then
    if grep -Fxq '#[multilib]' /etc/pacman.conf; then
      sudo sed -i '/^#\[multilib\]$/{s/^#//;n;s/^#Include/Include/}' /etc/pacman.conf
    else
      printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' | sudo tee -a /etc/pacman.conf >/dev/null
    fi
  fi
  sudo pacman -Syu --needed --noconfirm "${packages[@]}"
else
  printf '==> Native packages are present\n'
fi

# 2. Nix, the daemon, wheel and yay.
nix_conf=/etc/nix/nix.conf
if [[ ! -f $nix_conf ]] || ! grep -Fq experimental-features "$nix_conf"; then
  sudo mkdir -p /etc/nix
  printf 'experimental-features = nix-command flakes\n' | sudo tee -a "$nix_conf" >/dev/null
fi
# Write the block arch-switch owns, so deployment adopts it instead of adding a
# second trusted-users entry.
if ! grep -Fq trusted-users "$nix_conf"; then
  printf '# BEGIN nix-config settings\ntrusted-users = root @wheel %s\n# END nix-config settings\n' \
    "$login_user" | sudo tee -a "$nix_conf" >/dev/null
fi
sudo systemctl enable --now nix-daemon.service

joined_wheel=0
if ! id -nG "$login_user" | tr ' ' '\n' | grep -Fxq wheel; then
  sudo gpasswd -a "$login_user" wheel
  joined_wheel=1
fi

if ! command -v yay &>/dev/null; then
  printf '==> Installing yay-bin from AUR...\n'
  yay_dir=$(mktemp -d "/tmp/yay-bin.XXXXXX")
  git clone https://aur.archlinux.org/yay-bin.git "$yay_dir"
  (cd "$yay_dir" && makepkg -si --noconfirm)
  rm -rf "$yay_dir"
fi

# 3. The newest release tag, and the checkout.
remote=${NACRE_TEST_RELEASE_REMOTE:-https://github.com/abnertu/nacre}
tag=$(git ls-remote --tags --refs "$remote" 'v*' |
  sed -n 's#.*refs/tags/\(v[0-9]*\.[0-9]*\.[0-9]*\)$#\1#p' | sort -V | tail -n 1)
[[ -n $tag ]] || {
  printf 'error: no Nacre release tag found at %s\n' "$remote" >&2
  exit 1
}

config_home=${XDG_CONFIG_HOME:-$HOME/.config}
if [[ -n ${NACRE_DIR:-} ]]; then
  checkout=$NACRE_DIR
  [[ -e $checkout/flake.nix ]] || {
    printf 'error: NACRE_DIR=%s has no flake.nix\n' "$checkout" >&2
    exit 1
  }
elif [[ -e $config_home/nacre/flake.nix ]]; then
  checkout=$config_home/nacre
elif [[ -e $config_home/nix/flake.nix ]]; then
  checkout=$config_home/nix
else
  checkout=$config_home/nacre
fi

# 4. Upgrade an existing checkout, or install a new one.
command=(nix run "github:abnertu/nacre/$tag#nacre" -- --dir "$checkout")
if [[ -e $checkout/flake.nix ]]; then
  command+=(upgrade self)
  if [[ -n ${NACRE_REPO:-} ]]; then
    origin=$(git -C "$checkout" remote get-url origin 2>/dev/null || true)
    [[ $origin == "$NACRE_REPO" ]] ||
      printf 'warning: %s has origin %s, not NACRE_REPO %s; upgrading it\n' \
        "$checkout" "${origin:-(none)}" "$NACRE_REPO" >&2
  fi
else
  command+=(install)
  [[ -z ${NACRE_REPO:-} ]] || command+=(--repo "$NACRE_REPO")
fi
yes=0
[[ ${NACRE_YES:-} != 1 ]] || { yes=1; command+=(--yes); }

printf '\n==> Prerequisites are ready. Nacre %s\n' "$tag"
if ((joined_wheel)); then
  # Deployment needs wheel in this session.
  printf 'You joined wheel. In a new login session, run:\n  %s\n' "${command[*]}"
elif ((yes)); then
  exec "${command[@]}"
elif [[ ! -t 0 || ! -t 1 ]]; then
  printf 'Without a terminal, run:\n  %s\nor rerun with NACRE_YES=1.\n' "${command[*]}"
else
  read -rp "Run ${command[*]}? [Y/n] " answer
  if [[ ${answer:-y} == [Yy]* ]]; then
    exec "${command[@]}"
  fi
  printf 'Later: %s\n' "${command[*]}"
fi
