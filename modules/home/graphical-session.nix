{
  lib,
  hardware,
  capabilities,
  ...
}:
let
  systemBin = "/usr/bin";
  bin = name: "${systemBin}/${name}";
  hyprpolkitagentExecutable = "/usr/lib/hyprpolkitagent/hyprpolkitagent";
  # Vesktop 1.6.7 on this Hyprland/Electron combination fails to remap a hidden
  # native Wayland window. Keep the workaround app-local, including CLI launches.
  vesktopPlatformFlag = "--ozone-platform=x11";
  graphicalUnit = {
    After = [ "graphical-session.target" ];
    PartOf = [ "graphical-session.target" ];
    ConditionEnvironment = [ "WAYLAND_DISPLAY" ];
  };
  trayConsumerUnit = graphicalUnit // {
    After = [
      "graphical-session.target"
      "noctalia.service"
    ];
    Wants = [ "noctalia.service" ];
  };
  waitForStatusNotifierWatcher = ''
    ${bin "bash"} -c 'deadline=$$((SECONDS + 10)); while (( SECONDS < deadline )); do ${bin "busctl"} --user --timeout=1s get-property org.kde.StatusNotifierWatcher /StatusNotifierWatcher org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems >/dev/null 2>&1 && exit 0; ${bin "sleep"} 0.1; done; exit 0'
  '';
  # Vicinae can run without a tray; timeout deliberately permits degraded startup.
  restartableService = {
    Restart = "on-failure";
    RestartSec = "2s";
    TimeoutStopSec = "5s";
  };
in
{
  systemd.user = {
    # Start new units, restart changed ones and stop removed ones; unchanged
    # units keep running.
    startServices = "sd-switch";

    # Noctalia's Kitty hook cannot touch the read-only kitty.conf, so running
    # Kitty windows reload here when Noctalia rewrites their theme.
    paths.kitty-theme-reload = {
      Unit.Description = "Watch the Noctalia Kitty theme";
      Path.PathChanged = "%h/.config/kitty/themes/noctalia.conf";
      Install.WantedBy = [ "graphical-session.target" ];
    };

    services = {
      kitty-theme-reload = {
        Unit.Description = "Reload running Kitty windows after a theme change";
        # No running Kitty is not a failure.
        Service = {
          Type = "oneshot";
          ExecStart = "-${bin "pkill"} --signal USR1 --exact kitty";
        };
      };
      hyprpolkitagent = lib.mkIf (capabilities.desktop.hyprpolkitagent.enable) {
        Unit = graphicalUnit // {
          Description = "Hyprland Polkit authentication agent";
        };
        Service = restartableService // {
          ExecStart = hyprpolkitagentExecutable;
          Slice = "session.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      vicinae = lib.mkIf (capabilities.programs.vicinae.enable) {
        Unit = trayConsumerUnit // {
          Description = "Vicinae launcher daemon";
          Documentation = [ "https://docs.vicinae.com" ];
          Requires = [ "dbus.socket" ];
          # Vicinae claims the watcher name when the shell disappears. Stop it
          # first (inverse After order), and restart it after the shell returns.
          BindsTo = [ "noctalia.service" ];
          PartOf = graphicalUnit.PartOf ++ [ "noctalia.service" ];
        };
        Service = {
          Type = "simple";
          Environment = [ "VICINAE_OVERRIDES=%h/.config/vicinae/nix-managed.json" ];
          ExecStartPre = waitForStatusNotifierWatcher;
          TimeoutStartSec = "15s";
          ExecStart = "${bin "vicinae"} server --replace";
          ExecReload = "${bin "kill"} -HUP $MAINPID";
          KillMode = "process";
          Restart = "always";
          RestartSec = "60s";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      noctalia = {
        Unit = graphicalUnit // {
          Description = "Noctalia desktop shell";
          Wants = lib.optional capabilities.programs.vicinae.enable "vicinae.service";
        };
        Service = restartableService // {
          ExecStart = bin "noctalia";
          Slice = "session-graphical.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      quickshell-overview = lib.mkIf (capabilities.desktop.overview.enable) {
        Unit = graphicalUnit // {
          Description = "Quickshell workspace overview";
        };
        Service = restartableService // {
          ExecStart = "${bin "quickshell"} -c overview";
          Slice = "session-graphical.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      polychromatic-tray = lib.mkIf hardware.openrazer {
        Unit = trayConsumerUnit // {
          Description = "Polychromatic tray applet";
          After = trayConsumerUnit.After ++ [ "openrazer-daemon.service" ];
          Wants = trayConsumerUnit.Wants ++ [ "openrazer-daemon.service" ];
        };
        Service = restartableService // {
          ExecStart = bin "polychromatic-tray-applet";
          Slice = "app-graphical.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      tailscale-systray = lib.mkIf (capabilities.tailscale && capabilities.desktop.tailscaleTray.enable) {
        Unit = trayConsumerUnit // {
          Description = "Tailscale systray";
        };
        Service = restartableService // {
          ExecStart = "${bin "tailscale"} systray";
          Slice = "app-graphical.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      vesktop = lib.mkIf (capabilities.programs.vesktop.enable) {
        Unit = trayConsumerUnit // {
          Description = "Vesktop communication client";
        };
        Service = restartableService // {
          ExecStartPre = "${bin "sleep"} 3";
          ExecStart = "${bin "vesktop"} --start-minimized ${vesktopPlatformFlag}";
          RestartSec = "5s";
          Slice = "app-graphical.slice";
          TimeoutStopSec = "10s";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };
    };
  };

  xdg.configFile = {
    # The Arch launcher reads this after electron-flags.conf. Do not force all
    # Electron applications onto XWayland or replace the native executable.
    "vesktop-flags.conf" = lib.mkIf capabilities.programs.vesktop.enable {
      text = "${vesktopPlatformFlag}\n";
    };
    "vicinae/nix-managed.json" = lib.mkIf capabilities.programs.vicinae.enable {
      text = builtins.toJSON {
        providers.applications.entrypoints = {
          kitty.preferences.defaultAction = "launch";
          vesktop.preferences.defaultAction = "launch";
        };
      };
    };
    "systemd/user/openrazer-daemon.service.d/delay.conf" = lib.mkIf hardware.openrazer {
      text = ''
        [Service]
        ExecStartPre=${bin "sleep"} 20
      '';
    };
    "systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/override.conf" =
      lib.mkIf capabilities.programs.sunshine.enable
        {
          text = ''
            [Service]
            Restart=on-failure
            RestartSec=5s

            [Install]
            WantedBy=graphical-session.target
          '';
        };
  };
}
