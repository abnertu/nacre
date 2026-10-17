{ lib, pkgs }:
let
  source = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../configuration.nix
      ../flake.nix
      ../pyproject.toml
      ../lib
      ../hosts
      ../homes
      ../profiles
      ../platforms
      ../modules
      ../checks
    ];
  };
in
pkgs.runCommand "source-format-check"
  {
    nativeBuildInputs = [
      pkgs.nixfmt
      pkgs.ruff
      pkgs.findutils
    ];
  }
  ''
    find ${source} -name '*.nix' -print0 | xargs -0 nixfmt --check
    ruff check --no-cache ${source}
    ruff format --no-cache --check ${source}
    touch "$out"
  ''
