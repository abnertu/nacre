# pyright strict over the production Python, standard over the tests.
{
  lib,
  pkgs,
  nixAdapter,
}:
let
  python = pkgs.python3.withPackages (packages: [
    packages.jinja2
    packages.rich
    nixAdapter
  ]);
  source = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../checks
      ../lib
      ../modules
      ../platforms
    ];
  };
in
pkgs.runCommand "python-type-check"
  {
    nativeBuildInputs = [ pkgs.pyright ];
  }
  ''
    cd ${source}
    pyright --pythonpath ${python}/bin/python
    touch "$out"
  ''
