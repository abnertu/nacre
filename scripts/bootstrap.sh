#!/usr/bin/env bash
# Standalone bootstrap script for fresh Arch Linux machines, runnable straight
# from GitHub:
#   bash <(curl -fsSL https://raw.githubusercontent.com/abnertu/nacre/main/scripts/bootstrap.sh)
# Prepares native dependencies (nix, just, yay, base-devel), configures
# /etc/nix/nix.conf, starts nix-daemon, validates wheel membership, then
# offers to create this machine's flake with nacre install.

set -euo pipefail

usage() {
  cat <<'EOF'
usage: bootstrap.sh [--help]

Prepare a fresh Arch Linux system for Nacre:
  1. Enables [multilib] and installs base-devel, git, nix, and just via pacman.
  2. Configures /etc/nix/nix.conf with flakes and trusted-users.
  3. Enables and starts nix-daemon.service.
  4. Adds the current login user to the wheel group.
  5. Installs yay (AUR helper) from yay-bin if not already present.
Then, on a terminal and without ~/.config/nacre, it offers to run
`nacre install` to create this machine's flake.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

if [[ ! -f /etc/arch-release ]]; then
  printf 'error: bootstrap.sh only supports Arch Linux\n' >&2
  exit 1
fi

if (( EUID == 0 )); then
  printf 'error: run bootstrap.sh as your regular login user with sudo privileges, not root\n' >&2
  exit 1
fi

login_user=$(id --user --name)
printf '==> Bootstrapping Arch Linux workstation for user: %s\n' "$login_user"

# 1. Native base dependencies. Declared lib32 packages require [multilib].
printf '==> 1/5 Enabling [multilib] and installing native packages (base-devel, git, nix, just)...\n'
if ! pacman-conf --repo multilib Server >/dev/null 2>&1; then
  if grep -Fxq '#[multilib]' /etc/pacman.conf; then
    sudo sed -i '/^#\[multilib\]$/{s/^#//;n;s/^#Include/Include/}' /etc/pacman.conf
  else
    printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' | sudo tee -a /etc/pacman.conf >/dev/null
  fi
fi
sudo pacman -Syu --needed --noconfirm base-devel git nix just

# 2. Configure /etc/nix/nix.conf
printf '==> 2/5 Configuring /etc/nix/nix.conf for Flakes and trusted users...\n'
sudo mkdir -p /etc/nix
nix_conf="/etc/nix/nix.conf"

if [[ ! -f $nix_conf ]] || ! grep -Fq "experimental-features" "$nix_conf"; then
  printf 'experimental-features = nix-command flakes\n' | sudo tee -a "$nix_conf" >/dev/null
fi

# Write the block arch-switch owns, so deployment adopts it instead of adding a
# second trusted-users entry.
if ! grep -Fq "trusted-users" "$nix_conf"; then
  printf '# BEGIN nix-config settings\ntrusted-users = root @wheel %s\n# END nix-config settings\n' \
    "$login_user" | sudo tee -a "$nix_conf" >/dev/null
fi

# 3. Enable and start nix-daemon
printf '==> 3/5 Enabling and starting nix-daemon.service...\n'
sudo systemctl enable --now nix-daemon.service

# 4. User group membership
printf '==> 4/5 Ensuring user belongs to wheel...\n'
joined_wheel=0
if ! id -nG "$login_user" | tr ' ' '\n' | grep -Fxq wheel; then
  sudo gpasswd -a "$login_user" wheel
  joined_wheel=1
  printf 'Note: %s added to wheel. You may need to log out or run "exec su -l %s" for new group membership to take effect.\n' "$login_user" "$login_user"
fi

# 5. Install yay (AUR helper)
printf '==> 5/5 Checking yay (AUR helper)...\n'
if ! command -v yay &>/dev/null; then
  printf 'Installing yay-bin from AUR...\n'
  yay_dir=$(mktemp -d "/tmp/yay-bin.XXXXXX")
  git clone https://aur.archlinux.org/yay-bin.git "$yay_dir"
  (cd "$yay_dir" && makepkg -si --noconfirm)
  rm -rf "$yay_dir"
else
  printf 'yay is already installed: %s\n' "$(command -v yay)"
fi

printf '\n==> Bootstrap completed successfully!\n'
install=(nix run github:abnertu/nacre#nacre -- install)
config_home=${XDG_CONFIG_HOME:-$HOME/.config}
if [[ -e $config_home/nacre/flake.nix ]]; then
  printf 'Existing machine flake: cd %s/nacre && nix run .#nacre -- plan, then update\n' "$config_home"
elif ((joined_wheel)) || [[ ! -t 0 || ! -t 1 ]]; then
  # Deployment needs wheel in this session, and install asks questions.
  printf 'Next, in a new login session: %s\n' "${install[*]}"
else
  read -rp "Create this machine's flake now with nacre install? [Y/n] " answer
  if [[ ${answer:-y} == [Yy]* ]]; then
    exec "${install[@]}"
  fi
  printf 'Later: %s\n' "${install[*]}"
fi
