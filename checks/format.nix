# Formatting check: nixfmt for Nix, ruff for Python, shfmt for shell.
{ lib, pkgs }:
let
  source = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../.editorconfig
      ../flake.nix
      ../pyproject.toml
      ../lib
      ../profiles
      ../platforms
      ../modules
      ../checks
      ../roles
      ../scripts
      ../templates/machine/flake.nix
    ];
  };
in
pkgs.runCommand "source-format-check"
  {
    nativeBuildInputs = [
      pkgs.nixfmt
      pkgs.ruff
      pkgs.findutils
      pkgs.shfmt
    ];
  }
  ''
    find ${source} -name '*.nix' -print0 | xargs -0 nixfmt --check
    ruff check --no-cache ${source}
    ruff format --no-cache --check ${source}
    # shfmt takes its options from .editorconfig.
    cd ${source}
    find . \( -name '*.sh' -o -name '*.bash' \) -print0 | xargs -0 shfmt --diff
    touch "$out"
  ''
