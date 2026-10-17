{ pkgs, adapterPython }:
pkgs.runCommand "noctalia-config-tests" { } ''
  ${adapterPython}/bin/python ${./tests/test_sync.py} ${./sync.py}
  touch "$out"
''
