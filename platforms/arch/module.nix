# Arch realization interface: features contribute native names here, and the
# deployment reads only the merged result. Capabilities without a feature
# module of their own contribute from this file.
{ config, lib, ... }:
let
  inherit (lib) mkOption types optionals;
  names =
    description:
    mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      inherit description;
    };
  desktop = config.desktop.enable;
in
{
  options.arch = {
    pacman = names "Arch repository packages.";
    aur = names "AUR packages, installed through yay as the login user.";
    lizardbyte = names "Packages from the managed LizardByte repository.";
    hold = names "Installed packages update must not upgrade.";
    groups = names "Groups the deployment user must belong to.";
    systemUnits = names "System units to enable and keep active.";
    userServices = names "Packaged user units to enable for the deployment user.";
  };

  config.arch = {
    inherit (config.packages) hold;
    pacman =
      config.packages.extra.pacman
      ++ [
        "base-devel"
        "ca-certificates"
        "ca-certificates-utils"
        "coreutils"
        "curl"
        "dnsmasq"
        "hostapd"
        "i2c-tools"
        "inxi"
        "iproute2"
        "libnewt"
        "libva-utils"
        "linux-headers"
        "mtr"
        "nvtop"
        "pacman-contrib"
        "p11-kit"
        "procps-ng"
        "realtime-privileges"
        "rt-tests"
        "rtirq"
        "schedtool"
        "shadow"
        "systemd"
        "tuna"
        "util-linux"
        "vulkan-tools"
        "yt-dlp"
        "zsh"
      ]
      ++ optionals config.networking.networkmanager.enable [
        "network-manager-applet"
        "networkmanager"
        "networkmanager-openconnect"
        "networkmanager-openvpn"
        "nm-connection-editor"
      ]
      ++ optionals config.hardware.bluetooth.enable [
        "bluez"
        "bluez-utils"
        "blueman"
      ]
      ++ optionals config.services.powerProfilesDaemon.enable [ "power-profiles-daemon" ]
      ++ optionals config.services.tailscale.enable [ "tailscale" ]
      ++ optionals desktop [
        "adobe-source-code-pro-fonts"
        "adw-gtk-theme"
        "adwaita-cursors"
        "adwaita-fonts"
        "adwaita-icon-theme"
        "baobab"
        "brightnessctl"
        "cliphist"
        "ddcutil"
        "fcitx5"
        "fcitx5-chewing"
        "fcitx5-configtool"
        "fcitx5-gtk"
        "fcitx5-qt"
        "ffmpegthumbnailer"
        "grim"
        "gvfs"
        "gvfs-mtp"
        "hyprland"
        "noctalia"
        "hypridle"
        "hyprlock"
        "hyprpolkitagent"
        "hyprsunset"
        "imagemagick"
        "inter-font"
        "kitty"
        "libnotify"
        "loupe"
        "mpv"
        "noto-fonts"
        "noto-fonts-emoji"
        "nwg-displays"
        "nwg-look"
        "otf-font-awesome"
        "papirus-icon-theme"
        "pavucontrol"
        "pipewire"
        "pipewire-alsa"
        "pipewire-audio"
        "pipewire-pulse"
        "playerctl"
        "qt5ct"
        "qt6-5compat"
        "qt6ct"
        "quickshell"
        "slurp"
        "swappy"
        "thunar"
        "thunar-archive-plugin"
        "thunar-volman"
        "ttf-droid"
        "ttf-fantasque-nerd"
        "ttf-fira-code"
        "ttf-firacode-nerd"
        "ttf-jetbrains-mono"
        "ttf-jetbrains-mono-nerd"
        "tumbler"
        "uwsm"
        "wireplumber"
        "wl-clipboard"
        "xarchiver"
        "xdotool"
        "xdg-desktop-portal-gtk"
        "xdg-desktop-portal-hyprland"
        "xdg-user-dirs"
        "yad"
      ]
      ++ optionals (config.networking.networkmanager.enable && config.networking.hotspot.enable) [ "iw" ]
      ++ optionals config.networking.firewall.enable [ "ufw" ]
      ++ optionals (config.hardware.graphics == "amd") [
        "amd-ucode"
        "amdgpu_top"
        "lib32-vulkan-radeon"
        "vulkan-radeon"
      ]
      ++ optionals (config.hardware.openrazer.enable && desktop) [
        "openrazer-daemon"
        "openrazer-driver-dkms"
      ]
      ++ optionals config.i18n.enable [ "glibc" ]
      ++ optionals config.time.enable [ "tzdata" ]
      ++ optionals config.console.enable [ "kbd" ];

    lizardbyte = optionals (desktop && config.programs.sunshine.enable) [ "sunshine" ];

    aur =
      config.packages.extra.aur
      ++ optionals desktop [
        "bibata-cursor-theme-bin"
        "mpv-mpris"
        "mpvpaper"
        "noto-fonts-tc-vf"
        "ttf-victor-mono"
        "zen-browser-bin"
      ]
      ++ optionals (desktop && config.programs.vesktop.enable) [ "vesktop-bin" ]
      ++ optionals (desktop && config.programs.vicinae.enable) [ "vicinae-bin" ]
      ++ optionals (config.hardware.openrazer.enable && desktop) [ "polychromatic" ];

    systemUnits =
      optionals config.networking.networkmanager.enable [ "NetworkManager.service" ]
      ++ optionals config.hardware.bluetooth.enable [ "bluetooth.service" ]
      ++ optionals config.services.powerProfilesDaemon.enable [ "power-profiles-daemon.service" ]
      ++ optionals config.services.tailscale.enable [ "tailscaled.service" ];

    userServices =
      optionals (config.hardware.openrazer.enable && desktop) [ "openrazer-daemon.service" ]
      ++ optionals (desktop && config.programs.sunshine.enable) [
        "app-dev.lizardbyte.app.Sunshine.service"
      ];
  };
}
