# Exercise the selective source entry point with public synthetic documents.
{ lib, pkgs }:
let
  root = ../../../checks/fixtures/runner-public;
  capture = configFiles: import ../public-files.nix { inherit lib root configFiles; };
  selected = [
    "instances/frontend.toml"
    "instances/dotnet.toml"
  ];
  packaged = capture selected;
  # Record the real executable boundary. No native command is reachable.
  controller =
    pkgs.runCommand "synthetic-controller-package"
      {
        script = ''
          #!${pkgs.python3}/bin/python3
          import json
          import os
          import sys

          print(json.dumps({
              "argv": sys.argv[1:],
              "environment": os.environ.get("NACRE_RUNNER_TEST"),
              "cwd": os.getcwd(),
          }))
          print("synthetic controller stderr", file=sys.stderr)
          sys.exit(int(os.environ["NACRE_RUNNER_TEST_EXIT"]))
        '';
        passAsFile = [ "script" ];
      }
      ''
        install -Dm755 "$scriptPath" "$out/bin/runnerctl"
      '';
  configured = import ../configured-controller.nix {
    inherit
      lib
      pkgs
      root
      controller
      ;
    configFiles = selected;
  };
  rejects = configFiles: !(builtins.tryEval (builtins.deepSeq (capture configFiles) true)).success;
  rootLinkRejected =
    !(builtins.tryEval (
      builtins.deepSeq (import ../public-files.nix {
        inherit lib;
        root = root + "/root-link";
        configFiles = [ "common.toml" ];
      }) true
    )).success;
in
assert rootLinkRejected;
assert lib.all rejects [
  [ ]
  [ "/synthetic-outside.toml" ]
  [ "../synthetic-outside.toml" ]
  [ "frontend-link.toml" ]
  [ "invalid/directory-link/common.toml" ]
  [ "instances/frontend.toml/" ]
  [ "instances/frontend.toml/." ]
  [ "instances/frontend.toml/../frontend.toml" ]
  [ "instances/unselected.txt" ]
  [ "instances/Not-valid.toml" ]
  [ "instances/not-present.toml" ]
  [
    "instances/frontend.toml"
    "instances/./frontend.toml"
  ]
  [
    "instances/frontend.toml"
    "invalid/frontend.toml"
  ]
  [ "invalid/child.toml" ]
  [ "invalid/absolute-base.toml" ]
  [ "invalid/escape-base.toml" ]
  [ "invalid/absolute-ca.toml" ]
  [ "invalid/escape-ca.toml" ]
  [ "invalid/missing.toml" ]
  [ "invalid/directory.toml" ]
  [ "invalid/symlink-base.toml" ]
  [ "invalid/symlink-ca.toml" ]
  [ "invalid/symlink-parent.toml" ]
  [ "invalid/symlink-dotdot.toml" ]
  [ "invalid/wrong-base.toml" ]
  [ "invalid/wrong-ca.toml" ]
  [ "invalid/wrong-table.toml" ]
];
pkgs.runCommand "runner-public-files" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  python ${./test_public_files.py} ${packaged.source} ${lib.escapeShellArgs packaged.configFiles}
  python ${./test_configured_controller.py} ${configured}/bin/runnerctl ${lib.escapeShellArgs packaged.configFiles}
  mkdir -p "$out"
  # Expose only the selective source to callers of this check. The original
  # fixture root must not become a derivation input.
  ln -s ${packaged.source} "$out/source"
''
