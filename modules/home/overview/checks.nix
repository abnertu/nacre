# Tests of the Quickshell overview's refresh and query logic.
{ pkgs }:
pkgs.runCommand "overview-refresh-tests"
  {
    nativeBuildInputs = [
      pkgs.nodejs
      pkgs.python3
    ];
  }
  ''
    node ${./tests/test_refresh.js} ${../../../files/home/.config/quickshell/overview/services/Refresh.js}
    python ${./tests}/test_query.py ${../../../files/home/.config/quickshell/overview/services} ${pkgs.qt6.qtdeclarative}/bin/qmltestrunner
    touch "$out"
  ''
