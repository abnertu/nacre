{
  lib,
  pkgs,
  deploymentUser,
  username,
  # Merged native contributions: the evaluated configuration's `arch` option.
  arch,
  hardware,
  capabilities,
  systemSettings,
  aiConfig ? null,
  aiArtifacts ? null,
  sysctl ? { },
  kernelModules ? [ ],
  nixSettings ? { },
  powerpanel ? null,
  adapterPython ? pkgs.python3,
}:
let
  source =
    name:
    lib.fileset.toSource {
      root = ./. + "/${name}";
      # Every module beside the adapter, without its tests.
      fileset = lib.fileset.difference (lib.fileset.fileFilter (file: file.hasExt "py") (
        ./. + "/${name}"
      )) (lib.fileset.maybeMissing (./. + "/${name}/tests"));
    };
  core = import ./core {
    inherit
      lib
      pkgs
      username
      deploymentUser
      hardware
      capabilities
      arch
      sysctl
      kernelModules
      nixSettings
      powerpanel
      ;
    ownedUnits = lib.concatMap (extension: extension.ownedUnits) (builtins.attrValues arch.extensions);
  };
  # Without llama.cpp the AI adapter manages nothing; it gets the unmanaged manifest.
  ai =
    if aiConfig == null || !(aiConfig.enable && aiConfig.llama.enable) then
      null
    else
      import ./ai {
        inherit lib pkgs;
        config = aiConfig;
        artifacts = aiArtifacts;
        tailscale = capabilities.tailscale;
      };
  # One manifest per adapter; checks validate them against the Python schemas.
  manifests = {
    core = core.manifestFile;
    system = systemSettings.manifest;
    ai =
      if ai == null then
        pkgs.writeText "unmanaged-ai.json" (builtins.toJSON { llama = false; })
      else
        ai.manifest;
  }
  // lib.mapAttrs (
    name: extension: pkgs.writeText "arch-${name}.json" (builtins.toJSON extension.manifest)
  ) arch.extensions;
in
(pkgs.runCommand "arch-switch"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "arch-switch";
    config = builtins.toJSON {
      fsRoot = "";
      nativeBin = "/usr/bin";
      adapterPython = "${adapterPython}/bin/python3";
      adapters = {
        core = {
          adapter = "${source "core"}/adapter.py";
          manifest = manifests.core;
        };
        system = {
          adapter = "${source "system"}/adapter.py";
          manifest = manifests.system;
        };
        ai = {
          adapter = "${source "ai"}/adapter.py";
          manifest = manifests.ai;
        };
      }
      // lib.mapAttrs (name: extension: {
        adapter = "${extension.adapter}";
        manifest = manifests.${name};
      }) arch.extensions;
      # Machine-provided optional adapters, run after the built-in ones.
      extensions = lib.mapAttrsToList (name: extension: {
        inherit name;
        inherit (extension) label requires notReady;
      }) arch.extensions;
      lizardbyteConf = "${./files/pacman-lizardbyte.conf}";
      curl = "${pkgs.curl}/bin/curl";
      tar = "${pkgs.libarchive}/bin/bsdtar";
      expectedUser = username;
      inherit (arch)
        pacman
        lizardbyte
        aur
        hold
        ;
      userServices = arch.userServices;
    };
    passAsFile = [ "config" ];
  }
  ''
    mkdir -p "$out/bin" "$out/share/arch-switch"
    cp "$configPath" "$out/share/arch-switch/config.json"
    makeWrapper ${adapterPython}/bin/python3 "$out/bin/arch-switch" \
      --add-flags "-I ${./switch.py} --config $out/share/arch-switch/config.json"
  ''
)
// {
  inherit manifests;
}
