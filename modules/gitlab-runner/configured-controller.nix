# One configured CLI for operator commands and the deployment adapter.
{
  lib,
  pkgs,
  controller,
  root,
  configFiles,
}:
let
  public = import ./public-files.nix { inherit lib root configFiles; };
  arguments = lib.concatMap (file: [
    "--config"
    file
  ]) public.configFiles;
in
pkgs.writeShellScriptBin "runnerctl" ''
  exec ${lib.escapeShellArg (lib.getExe' controller "runnerctl")} --platform arch ${lib.escapeShellArgs arguments} "$@"
''
