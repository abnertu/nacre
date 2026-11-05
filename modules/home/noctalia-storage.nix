# Noctalia's file-based key storage configuration.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  keyFile = "${config.xdg.dataHome}/noctalia/file-key-v1/master-key";
in
{
  # Only the runtime filename enters the store, never the generated key.
  xdg.configFile."noctalia/storage.toml".text = ''
    [storage]
    key_source = "file"
    key_file = ${builtins.toJSON keyFile}

    [calendar]
    enabled = false
  '';

  home.activation.ensureNoctaliaStorageKey =
    lib.hm.dag.entryBetween [ "linkGeneration" ] [ "writeBoundary" ]
      ''
        if [ ! -f ${lib.escapeShellArg keyFile} ]; then
          mkdir -m 0700 -p $(dirname ${lib.escapeShellArg keyFile})
          ${pkgs.openssl}/bin/openssl rand -hex 32 > ${lib.escapeShellArg keyFile}.tmp
          chmod 0600 ${lib.escapeShellArg keyFile}.tmp
          mv -n ${lib.escapeShellArg keyFile}.tmp ${lib.escapeShellArg keyFile}
        fi
      '';
}
