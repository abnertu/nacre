# Arch realization interface: features contribute native names here, and the
# deployment reads only the merged result. Capabilities without a feature
# module of their own contribute from this file.
{ config, lib, ... }:
let
  inherit (lib) mkOption types optionals;
  desktop = config.desktop.enable;
  baseline = lib.mkOverride 1100;
  files = ./files;
  # Paths that other owners write; environment.etc must not name them.
  # A trailing slash reserves a directory and everything under it.
  reservedPaths = [
    # Core: the repository, managed blocks and account databases.
    "pacman.conf"
    "pacman.d/nix-config-lizardbyte.conf"
    "nix/nix.conf"
    "mkinitcpio.conf"
    "passwd"
    "group"
    "shadow"
    "gshadow"
    "subuid"
    "subgid"
    # System settings.
    "locale.conf"
    "locale.gen"
    "localtime"
    "hostname"
    "vconsole.conf"
    "systemd/timesyncd.conf.d/60-nix-config.conf"
    "systemd/journald.conf.d/60-nix-config.conf"
    "systemd/logind.conf.d/60-nix-config.conf"
    "systemd/system/fstrim.timer.d/60-nix-config.conf"
    "default/ufw"
    "ufw/"
    # AI.
    "caddy/Caddyfile"
    "caddy/conf.d/nix-config-llama.caddy"
    "llama-swap/"
    "systemd/system/llama-swap.service"
  ];
  relative = path: lib.removePrefix "/etc/" path;
in
{
  options.arch = {
    pacman = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "Arch repository packages.";
    };
    aur = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "AUR packages, installed through yay as the login user.";
    };
    lizardbyte = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "Packages from the managed LizardByte repository.";
    };
    hold = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "Installed packages update must not upgrade.";
    };
    groups = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "Groups the deployment user must belong to.";
    };
    systemUnits = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "System units to enable and keep active.";
    };
    userServices = mkOption {
      type = types.listOf types.str;
      default = [ ];
      apply = lib.unique;
      internal = true;
      description = "Packaged user units to enable for the deployment user.";
    };
    etc = mkOption {
      type = types.listOf types.attrs;
      internal = true;
      readOnly = true;
      description = "Enabled environment.etc entries with their resolved content, for the core manifest.";
    };
    etcReserved = mkOption {
      type = types.listOf types.str;
      internal = true;
      readOnly = true;
      description = "Paths relative to /etc that another owner writes; a trailing slash reserves a directory.";
    };
    extensions = mkOption {
      default = { };
      description = ''
        Optional privileged adapters from features or machine flakes.
        arch-switch runs preflight, plan and convergence for ready adapters.
        Explicit purge invokes only adapters that opt in through purge.
      '';
      type = types.attrsOf (
        types.submodule {
          options = {
            label = mkOption {
              type = types.str;
              description = "Name shown in progress and skip messages.";
            };
            adapter = mkOption {
              type = types.path;
              description = "Python adapter run as `adapter MANIFEST PHASE`; it exits 20 while not prepared.";
            };
            manifest = mkOption {
              type = types.attrsOf types.anything;
              description = "Manifest passed to the adapter as JSON.";
            };
            requires = mkOption {
              type = types.listOf (types.enum [ "ai" ]);
              default = [ ];
              description = "Built-in optional modules that must be ready first.";
            };
            notReady = mkOption {
              type = types.str;
              default = "preparation has not completed";
              description = "Skip reason while the adapter reports not ready.";
            };
            purge = mkOption {
              type = types.bool;
              default = false;
              description = "Run the adapter's purge phase before built-in retirement; failures stop purge.";
            };
            reservedPaths = mkOption {
              type = types.listOf types.str;
              default = [ ];
              description = ''
                Paths under /etc that the adapter writes itself, relative to /etc.
                A trailing slash reserves a directory. environment.etc cannot name them.
              '';
            };
            ownedUnits = mkOption {
              type = types.listOf (
                types.submodule {
                  options = {
                    unit = mkOption {
                      type = types.str;
                      description = "Unit name, such as babu.service.";
                    };
                    path = mkOption {
                      type = types.str;
                      description = "Unit file that purge removes, under /etc/systemd/system.";
                    };
                  };
                }
              );
              default = [ ];
              description = "System units in /etc/systemd/system that purge retires.";
            };
          };
        }
      );
    };
  };

  config.environment.etc = {
    "NetworkManager/conf.d/main.conf" = lib.mkIf config.networking.networkmanager.enable {
      source = baseline (files + "/NetworkManager-main.conf");
      adopt = baseline true;
      action = "network";
    };
    "NetworkManager/conf.d/99-tailscale.conf" =
      lib.mkIf (config.networking.networkmanager.enable && config.services.tailscale.enable)
        {
          source = baseline (files + "/NetworkManager-tailscale.conf");
          adopt = baseline true;
          action = "network";
        };
    # Derived from typed options at normal priority: change those options instead.
    "modules-load.d/nix-config-podman.conf" = {
      text = lib.concatMapStrings (module: "${module}\n") config.boot.kernelModules;
      adopt = baseline true;
    };
    "sysctl.d/99-nix-config.conf" = {
      text = lib.concatStrings (
        lib.mapAttrsToList (key: value: "${key} = ${toString value}\n") (
          lib.filterAttrs (_: value: value != null) config.boot.kernel.sysctl
        )
      );
      adopt = baseline true;
    };
    "systemd/system/getty@tty1.service.d/override.conf" = lib.mkIf desktop {
      text = lib.replaceStrings [ "@USER@" ] [ config.deployment.username ] (
        builtins.readFile (files + "/tty1-autologin.conf")
      );
      adopt = baseline true;
      action = "units";
    };
  };

  config.arch = {
    etc = lib.mapAttrsToList (name: entry: {
      inherit name;
      path = "/etc/${name}";
      text = entry.content;
      inherit (entry)
        mode
        group
        adopt
        action
        ;
    }) (lib.filterAttrs (_: entry: entry.enable && entry.content != null) config.environment.etc);
    etcReserved =
      reservedPaths
      ++ lib.concatMap (
        extension: extension.reservedPaths ++ map (owned: relative owned.path) extension.ownedUnits
      ) (builtins.attrValues config.arch.extensions);
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
        "ghostty"
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
