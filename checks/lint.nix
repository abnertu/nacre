# Source lint beyond formatting: unused Nix bindings, shell script defects and
# broken relative Markdown links or anchors. External URLs are not fetched.
{ lib, pkgs }:
let
  source = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.gitTracked ../.;
  };
in
pkgs.runCommand "source-lint"
  {
    nativeBuildInputs = [
      pkgs.deadnix
      pkgs.findutils
      pkgs.lychee
      pkgs.shellcheck
    ];
    # lychee builds an HTTP client even offline; it never fetches here.
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  }
  ''
    cd ${source}
    find . -name '*.nix' -not -path './files/*' -print0 | xargs -0 deadnix --fail
    shellcheck -x scripts/*.sh lib/cli/nix.sh lib/cli/progress/progress.sh
    find . -name '*.md' -not -path './files/*' -print0 |
      xargs -0 lychee --offline --no-progress --include-fragments
    touch "$out"
  ''
