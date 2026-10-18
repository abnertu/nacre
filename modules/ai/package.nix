{
  lib,
  pkgs,
  artifacts,
  adapterPython ? pkgs.python3,
}:
pkgs.runCommand "llama-prepare"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "llama-prepare";
    config = builtins.toJSON {
      source = {
        inherit (artifacts.source) repository revision installPrefix;
        grammarThreshold = artifacts.source.grammarRepetitionThreshold;
      };
      models = map (model: {
        inherit (model)
          repository
          revision
          file
          path
          sha256
          ;
      }) (builtins.attrValues artifacts.models);
      lock = "/run/lock/nacre-llama-prepare.lock";
      workBase = "/var/tmp";
      requireRoot = true;
      checkToolchain = true;
      rootOwnership = true;
    };
    passAsFile = [ "config" ];
  }
  ''
    mkdir -p "$out/bin" "$out/share/llama-prepare"
    cp "$configPath" "$out/share/llama-prepare/config.json"
    makeWrapper ${adapterPython}/bin/python3 "$out/bin/llama-prepare" \
      --add-flags "-I ${./prepare.py} --config $out/share/llama-prepare/config.json" \
      --prefix PATH : ${
        lib.makeBinPath (
          with pkgs;
          [
            cmake
            git
            ninja
            python3Packages.huggingface-hub
          ]
        )
      }
  ''
