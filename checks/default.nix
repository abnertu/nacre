{
  pkgs,
  lib,
  arch-switch,
  archDeployment,
  deploymentName,
}:
{
  home-source-assets = import ./assets.nix { inherit pkgs; };
  # actionlint also runs shellcheck on each workflow `run` script.
  workflow =
    pkgs.runCommand "github-workflow-check"
      {
        nativeBuildInputs = [
          pkgs.actionlint
          pkgs.shellcheck
        ];
      }
      ''
            actionlint ${../.github/workflows}/*.yml
        touch "$out"
      '';
  deployment-ordering =
    pkgs.runCommand "deployment-ordering"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.bash
          pkgs.coreutils
        ];
      }
      ''
        python ${../lib/deployment/tests/test_deployment.py} ${../lib/deployment/deploy.sh} ${../lib/deployment/home/switch.sh}
        touch "$out"
      '';
  arch-switch-interface = pkgs.runCommand "arch-switch-interface-check" { } ''
    # The wrapped executables start and reject conflicting modes.
    ${arch-switch}/bin/arch-switch --help >/dev/null
    if ${arch-switch}/bin/arch-switch --check --update >/dev/null 2>&1; then exit 1; fi
    ${archDeployment}/bin/${deploymentName} --help >/dev/null
    if ${archDeployment}/bin/${deploymentName} --plan --update >/dev/null 2>&1; then exit 1; fi
    touch "$out"
  '';
  justfile =
    let
      source = lib.fileset.toSource {
        root = ../.;
        fileset = lib.fileset.unions [
          ../Justfile
          ../lib/cli/nix.sh
          ./tests/test_cli.py
        ];
      };
    in
    pkgs.runCommand "justfile-check"
      {
        nativeBuildInputs = [
          pkgs.bash
          pkgs.coreutils
          pkgs.just
          pkgs.python3
        ];
      }
      ''
        python ${source}/checks/tests/test_cli.py ${source}
        touch "$out"
      '';
}
