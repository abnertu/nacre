{
  pkgs,
  home,
  inputs,
  user,
  adapterPython,
}:
let
  lib = pkgs.lib;
  fixtures = import ../../checks/lib.nix { inherit inputs lib; };
  # A minimal session home; the full variant adds OpenRazer and Noctalia storage.
  fixture =
    full:
    let
      username = if full then "tester" else "second";
    in
    fixtures.home [
      {
        hardware.openrazer.enable = full;
        users.users.${username} = fixtures.login {
          homeDirectory = if full then "/home/tester" else "/home/team/second";
          modules = [ "graphical-session" ] ++ lib.optional full "noctalia-storage";
        };
      }
    ] username;
  sessionFixture =
    full:
    let
      generated = fixture full;
    in
    {
      units = "${generated.activationPackage}/home-files/.config/systemd/user";
      expected = pkgs.writeText "session-expectations.json" (
        builtins.toJSON {
          home = generated.config.home.homeDirectory;
          storage = full;
          openrazer = full;
        }
      );
    };
in
{
  overview-refresh = import ./overview/checks.nix { inherit pkgs; };
  noctalia-config = import ./noctalia-config/checks.nix { inherit pkgs adapterPython; };
  graphical-session-ordering =
    pkgs.runCommand "graphical-session-ordering"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.bash
          pkgs.coreutils
        ];
      }
      ''
        ${lib.concatMapStringsSep "\n"
          (
            full:
            let
              f = sessionFixture full;
            in
            "python ${./tests/test_session.py} ${f.units} ${f.expected}"
          )
          [
            true
            false
          ]
        }
        touch "$out"
      '';
  home-projection =
    pkgs.runCommand "home-projection-check"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.bash
          pkgs.coreutils
        ];
      }
      ''
        python ${./tests/test_projection.py} ${./check-projection.sh}
        touch "$out"
      '';
  home-projection-interface =
    assert
      !(home.config.home.file ? ".zprofile")
      ||
        pkgs.lib.hasInfix "exec /usr/bin/uwsm start hyprland.desktop"
          home.config.home.file.".zprofile".text;
    assert !(home.config.xdg.configFile ? nvim) || !home.config.xdg.configFile.nvim.recursive;
    assert
      !(home.config.xdg.configFile ? hypr)
      || home.config.xdg.configFile.hypr.recursive
      || ((user.development.hyprlandPath or null) != null);
    assert builtins.all (
      name: !pkgs.lib.hasPrefix ".agents/skills/" name || !home.config.home.file.${name}.recursive
    ) (builtins.attrNames home.config.home.file);
    pkgs.writeText "home-projection-interface" "passed";
  home-development-mode =
    let
      devHome = fixtures.home [
        {
          users.users.tester = fixtures.login {
            homeDirectory = "/home/tester";
            profiles = [ "dev" ];
            modules = [ "hyprland" ];
            development = {
              neovimPath = "/home/tester/src/neovim";
              hyprlandPath = "/home/tester/src/hyprland";
            };
          };
        }
      ] "tester";
    in
    assert !devHome.config.xdg.configFile.hypr.recursive;
    assert devHome.config.xdg.configFile.hypr.source != inputs.hypr-config;
    assert devHome.config.xdg.configFile.nvim.source != inputs.nvim-config;
    pkgs.writeText "home-development-mode" "passed";
  home-config-sources =
    let
      hypr = pkgs.writeTextDir "hyprland.lua" "";
      nvim = pkgs.writeTextDir "init.lua" "";
      sourcedHome = fixtures.home [
        {
          users.users.tester = fixtures.login {
            homeDirectory = "/home/tester";
            profiles = [ "dev" ];
            modules = [ "hyprland" ];
            sources = {
              hyprland = hypr;
              neovim = nvim;
            };
          };
        }
      ] "tester";
    in
    assert sourcedHome.config.xdg.configFile.hypr.source == "${hypr}";
    assert sourcedHome.config.xdg.configFile.nvim.source == "${nvim}";
    pkgs.writeText "home-config-sources" "passed";
  arch-graphical-session = pkgs.runCommand "arch-graphical-session-check" { } ''
    units=${home.activationPackage}/home-files/.config/systemd/user
    profile=${home.config.home.path}
    for unit in \
      hyprpolkitagent.service \
      noctalia.service \
      polychromatic-tray.service \
      quickshell-overview.service \
      tailscale-systray.service \
      vesktop.service \
      vicinae.service; do
      [[ -f "$units/$unit" ]] || continue
      if ${pkgs.gnugrep}/bin/grep -Eq '^Exec(Start|StartPre|StartPost|Reload)=.*/nix/store/' "$units/$unit"; then
        printf 'Arch graphical unit references a Nix package: %s\n' "$unit" >&2
        exit 1
      fi
    done
    for executable in \
      ghostty \
      gimp \
      hypridle \
      hyprlock \
      hyprpolkitagent \
      hyprsunset \
      kitty \
      mpv \
      mpvpaper \
      noctalia \
      noctalia-shell \
      obs \
      quickshell \
      remmina \
      swappy \
      uwsm \
      vesktop \
      vicinae \
      vlc; do
      if [[ -e "$profile/bin/$executable" ]]; then
        printf 'Arch Home profile provides a native graphical executable: %s\n' "$executable" >&2
        exit 1
      fi
    done
    touch "$out"
  '';
}
