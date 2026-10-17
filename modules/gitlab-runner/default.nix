# Wire declared instance files to runnerctl, which owns validation, rendering
# and host reconciliation. Nix only pins runnerctl and copies the files.
{
  lib,
  pkgs,
  configFiles ? [ ],
  gitlab-runner ? null,
  ...
}:
let
  enabled = configFiles != [ ];
  # Files named inside a TOML file resolve relative to it, as runnerctl does.
  referenced =
    file:
    let
      document = builtins.fromTOML (builtins.readFile file);
      relative = name: dirOf file + "/${name}";
      base = lib.optional (document ? extends) (relative document.extends);
      certificate = lib.optional (document.gitlab.ca_certificate or null != null) (
        relative document.gitlab.ca_certificate
      );
    in
    base ++ certificate;
  closure = lib.unique (
    configFiles
    ++ lib.concatMap (file: referenced file ++ lib.concatMap referenced (referenced file)) configFiles
  );
  root = dirOf (builtins.head configFiles);
  source = lib.fileset.toSource {
    inherit root;
    fileset = lib.fileset.unions closure;
  };
  configArgs = lib.concatMapStringsSep " " (
    file: "-c ${lib.escapeShellArg "${source}/${lib.removePrefix "${toString root}/" (toString file)}"}"
  ) configFiles;
  controller = pkgs.writeShellApplication {
    name = "runnerctl";
    runtimeInputs = [ gitlab-runner.packages.${pkgs.stdenv.hostPlatform.system}.default ];
    text = ''
      exec runnerctl --platform arch ${configArgs} "$@"
    '';
  };
in
{
  packages = lib.optionalAttrs enabled { runnerctl = controller; };
  apps = lib.optionalAttrs enabled {
    runnerctl = {
      type = "app";
      program = "${controller}/bin/runnerctl";
      meta.description = "Manage dedicated rootless GitLab Runner instances";
    };
  };
  checks = lib.optionalAttrs enabled {
    gitlab-runner-config = pkgs.runCommand "gitlab-runner-config-check" { } ''
      ${controller}/bin/runnerctl validate > "$out"
    '';
  };
}
