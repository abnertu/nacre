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
  desktopPolicy = (fixtures.evaluate [ ]).config.arch;
  headlessPolicy = (fixtures.evaluate [ { desktop.enable = false; } ]).config.arch;
  packageNames = policy: policy.pacman ++ policy.aur ++ policy.lizardbyte;
  nativeDesktopPackages = map (lib.removeSuffix "-bin") (
    lib.subtractLists (packageNames headlessPolicy) (packageNames desktopPolicy)
  );
  nativeGraphicalUnits = builtins.attrNames (
    lib.filterAttrs (
      _: service: builtins.elem "graphical-session.target" (lib.toList (service.Unit.PartOf or [ ]))
    ) home.config.systemd.user.services
  );
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
  loginHome = fixtures.home [
    {
      users.users.login = fixtures.login {
        homeDirectory = "/home/login";
        modules = [ "hyprland" ];
      };
    }
  ] "login";
  loginProfile = pkgs.writeText "fixture-zprofile" loginHome.config.home.file.".zprofile".text;
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
          pkgs.zsh
        ];
      }
      ''
        python ${./tests/test_projection.py} ${./check-projection.sh} ${loginProfile}
        touch "$out"
      '';
  home-projection-interface =
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
  arch-graphical-session =
    let
      policy = pkgs.writeText "native-graphical-ownership.json" (
        builtins.toJSON {
          units = nativeGraphicalUnits;
          packages = nativeDesktopPackages;
          unitDirectory = "${home.activationPackage}/home-files/.config/systemd/user";
          profile = "${home.config.home.path}";
        }
      );
    in
    pkgs.runCommand "arch-graphical-session-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
      python - ${policy} <<'PY'
      import configparser
      import json
      import shlex
      import sys
      from pathlib import Path

      policy = json.loads(Path(sys.argv[1]).read_text())
      units, profile = Path(policy["unitDirectory"]), Path(policy["profile"])
      if not units.is_dir() or not (profile / "bin").is_dir():
          raise SystemExit("missing built graphical ownership input")
      forbidden = set(policy["packages"])
      for name in policy["units"]:
          for line in (units / (name + ".service")).read_text().splitlines():
              key, separator, value = line.partition("=")
              if separator and key in {"ExecStart", "ExecStartPre", "ExecStartPost", "ExecReload"} and value:
                  executable = shlex.split(value)[0].lstrip("-@:+!|")
                  if executable.startswith("/nix/store/"):
                      raise SystemExit(f"native graphical unit executes a Nix binary: {name}")
                  forbidden.add(Path(executable).name)
      for name in forbidden:
          if (profile / "bin" / name).exists():
              raise SystemExit(f"Home Manager supplies an Arch-owned executable: {name}")
      for path in (profile / "share/applications").glob("*.desktop"):
          desktop = configparser.RawConfigParser(strict=False)
          desktop.read(path)
          entry = desktop["Desktop Entry"]
          if entry.getboolean("Terminal", fallback=False) or entry.getboolean("NoDisplay", fallback=False):
              continue
          command = shlex.split(entry.get("Exec", ""))
          if not command:
              raise SystemExit(f"graphical desktop entry has no command: {path.name}")
          executable = Path(command[0])
          if not executable.is_absolute():
              executable = profile / "bin" / executable
          if str(executable.resolve()).startswith("/nix/store/"):
              raise SystemExit(f"Home Manager supplies a graphical desktop application: {path.name}")
      PY
      touch "$out"
    '';
}
