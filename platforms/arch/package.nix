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
  personalAgentPackage ? null,
  personalAgentConfig ? {
    enable = false;
  },
  sysctl ? { },
  kernelModules ? [ ],
  nixSettings ? { },
  powerpanel ? null,
  adapterPython ? pkgs.python3,
  progress ? import ../../lib/cli/progress { inherit pkgs adapterPython; },
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
  personalAgent =
    if personalAgentPackage == null then
      null
    else
      import ./personal-agent {
        inherit pkgs;
        package = personalAgentPackage;
        config = personalAgentConfig;
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
    personalAgent =
      if personalAgent == null then
        pkgs.writeText "unmanaged-personal-agent.json" (builtins.toJSON { enabled = false; })
      else
        personalAgent.manifest;
  };
in
(pkgs.writeShellApplication {
  name = "arch-switch";
  runtimeInputs = with pkgs; [
    coreutils
    gnugrep
  ];
  text = ''
    readonly adapter_python=${adapterPython}/bin/python3
    readonly core_adapter=${source "core"}/adapter.py
    readonly core_manifest=${manifests.core}
    readonly system_adapter=${source "system"}/adapter.py
    readonly system_manifest=${manifests.system}
    readonly ai_adapter=${source "ai"}/adapter.py
    readonly ai_manifest=${manifests.ai}
    readonly personal_agent_adapter=${./personal-agent/adapter.py}
    readonly personal_agent_manifest=${manifests.personalAgent}
    readonly fs_root=""
    readonly native_bin=/usr/bin
    readonly lizardbyte_conf=${./files/pacman-lizardbyte.conf}
    readonly curl_bin=${pkgs.curl}/bin/curl
    readonly tar_bin=${pkgs.libarchive}/bin/bsdtar
    readonly flock_bin=${pkgs.util-linux}/bin/flock
    readonly expected_user=${lib.escapeShellArg username}
    pacman_packages=(${lib.escapeShellArgs arch.pacman})
    lizardbyte_package_names=(${lib.escapeShellArgs arch.lizardbyte})
    lizardbyte_packages=(${lib.escapeShellArgs (map (name: "lizardbyte/${name}") arch.lizardbyte)})
    aur_packages=(${lib.escapeShellArgs arch.aur})
    user_services=(${lib.escapeShellArgs arch.userServices})
  ''
  + progress.shell
  + builtins.readFile ./arch-switch.sh;
})
// {
  inherit manifests;
}
