# Exercise real composition with a synthetic controller, never host state.
{
  inputs,
  pkgs,
  adapterPython,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;
  controller = pkgs.writeScriptBin "runnerctl" ''
    #!${pkgs.python3}/bin/python3
    import argparse
    import json
    import tomllib
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["arch"], required=True)
    parser.add_argument("--config", action="append", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("command", choices=["validate", "preflight", "plan", "reconcile", "purge"])
    parser.add_argument("instance", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    for file in args.config:
        document = tomllib.loads(file.read_text())
        base = file.parent / document["extends"]
        tomllib.loads(base.read_text())
    if args.command == "validate":
        print(json.dumps(sorted(file.stem for file in args.config)))
    else:
        assert args.instance in [file.stem for file in args.config]
        if args.command == "plan":
            assert args.json
            print(json.dumps([{"kind": "=", "text": "synthetic configured controller"}]))
  '';
  files = [
    ../../../checks/fixtures/runner-deployment/frontend.toml
    ../../../checks/fixtures/runner-deployment/dotnet.toml
  ];
  make =
    {
      enable ? null,
      configFiles ? files,
      selectedController ? controller,
      extra ? { },
    }:
    (import ../../../lib/mk-flake.nix {
      inputs = inputs // {
        gitlab-runner.packages.${system}.runnerctl = selectedController;
      };
    })
      {
        modules = [
          ../../../checks/fixtures/configuration.nix
          {
            services.gitlabRunner = {
              inherit configFiles;
            }
            // pkgs.lib.optionalAttrs (enable != null) { inherit enable; };
          }
          extra
        ];
      };
  enabled = make { enable = true; };
  disabled = make { };
  # A disabled deployment must not select the controller or read public TOML.
  lazy = make {
    configFiles = [ (builtins.toFile "unread-runner.toml" "[invalid TOML") ];
    selectedController = throw "disabled deployment evaluated its Runner controller";
  };
  without = make { configFiles = [ ]; };
  runner = make { extra.role = "runner"; };
  overridden = make {
    extra = {
      role = "runner";
      services.gitlabRunner.enable = pkgs.lib.mkDefault false;
      desktop.enable = pkgs.lib.mkDefault true;
      virtualization.kvm.enable = true;
    };
  };
  valid =
    arguments: (builtins.tryEval (make arguments).packages.${system}.arch-switch.drvPath).success;
in
assert enabled.apps.${system} ? runnerctl;
assert disabled.apps.${system} ? runnerctl;
assert !(without.apps.${system} ? runnerctl);
assert !(without.packages.${system} ? runnerctl);
assert !without.lib.configuration.services.gitlabRunner.enable;
assert runner.lib.configuration.services.gitlabRunner.enable;
assert runner.lib.configuration.virtualization.enable;
assert runner.lib.configuration.virtualization.podman.enable;
assert !runner.lib.configuration.virtualization.kvm.enable;
assert !runner.lib.configuration.virtualization.kvm.gui.enable;
assert !runner.lib.configuration.desktop.enable;
assert !overridden.lib.configuration.services.gitlabRunner.enable;
assert overridden.lib.configuration.desktop.enable;
assert overridden.lib.configuration.virtualization.kvm.enable;
assert builtins.attrNames runner.homeConfigurations == [ "fixture@fixture" ];
assert runner.homeConfigurations."fixture@fixture".config.home.stateVersion == "26.05";
assert
  !valid {
    extra.role = "runner";
    configFiles = [ ];
  };
assert
  !valid {
    extra = {
      role = "runner";
      virtualization.podman.enable = false;
    };
  };
assert valid { enable = true; };
assert
  !valid {
    enable = true;
    configFiles = [ ];
  };
assert
  !valid {
    enable = true;
    extra.virtualization.enable = false;
  };
assert
  !valid {
    enable = true;
    extra.virtualization.podman.enable = false;
  };
assert
  !valid {
    enable = true;
    configFiles = [
      ../../../checks/fixtures/runner-public/instances/frontend.toml
    ];
  };
assert
  !valid {
    enable = true;
    configFiles = [
      ../../../checks/fixtures/runner-deployment/frontend.toml
      ../../../checks/fixtures/runner-public/instances/dotnet.toml
    ];
  };
{
  inherit enabled disabled runner;
  check = pkgs.runCommand "runner-integration" { nativeBuildInputs = [ adapterPython ]; } ''
    python ${./test_adapter.py} ${pkgs.coreutils}/bin ${../adapter.py}
    python ${./test_feature.py} \
      ${enabled.packages.${system}.arch-switch} \
      ${disabled.packages.${system}.arch-switch} \
      ${enabled.apps.${system}.runnerctl.program} \
      ${disabled.apps.${system}.runnerctl.program} \
      ${pkgs.coreutils}/bin \
      ${../../../platforms/arch/tests} ${../../../platforms/arch/switch.py}
    mkdir -p "$out"
    ln -s ${lazy.packages.${system}.deployment} "$out/lazy-disabled-deployment"
    ln -s ${enabled.checks.${system}.gitlab-runner-config} "$out/enabled-config"
    ln -s ${disabled.checks.${system}.gitlab-runner-config} "$out/disabled-config"
    ln -s ${runner.packages.${system}.deployment} "$out/runner-role-deployment"
    ln -s ${runner.checks.${system}.gitlab-runner-config} "$out/runner-role-config"
  '';
}
