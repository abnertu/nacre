{
  lib,
  pkgs,
  inputs,
}:
let
  aiDefaults = {
    llama = {
      model = {
        device = "ROCm0";
        contextSize = 4096;
      };
    };
  };
  ai =
    raw:
    import ../modules/ai {
      inherit lib;
      config = import ../modules/ai/interface.nix {
        inherit lib;
        raw = lib.recursiveUpdate aiDefaults raw;
      };
      skillSources = {
        matt-pocock = inputs.matt-pocock-skills;
        vercel = inputs.vercel-skills;
      };
    };
  virtualization =
    raw:
    import ../modules/virtualization {
      inherit lib;
      config = import ../modules/virtualization/interface.nix { inherit lib raw; };
    };
  valid =
    name: raw:
    (builtins.tryEval (
      builtins.deepSeq (import (../modules + "/${name}/interface.nix") {
        inherit lib;
        raw = if name == "ai" then lib.recursiveUpdate aiDefaults raw else raw;
      }) true
    )).success;
  enabled = ai { enable = true; };
  profiled = ai {
    llama.profiles.coding = {
      enableThinking = true;
      temperature = 0.6;
    };
  };
  codexProfile = ai { enable = true; };
  codexProfileOff = ai {
    enable = true;
    codex.localProfile.enable = false;
  };
  codexOff = ai {
    enable = true;
    codex.enable = false;
  };
  llamaOff = ai {
    enable = true;
    llama.enable = false;
  };
  selectedCodexProfile = ai {
    enable = true;
    llama.model.name = "qwen3.5-4b-q4-k-m";
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      contextSize = 4096;
    };
    llama.models."qwen3.5-9b-q4-k-m" = {
      enable = true;
      contextSize = 16384;
    };
    llama.profiles.default.model = "qwen3.5-9b-q4-k-m";
  };
  codexProfileText =
    name: codex:
    pkgs.writeText "${name}.toml" codex.homeModule.home.file.".codex/llama-cpp.config.toml".text;
  codexProfileExpected =
    name: codex:
    pkgs.writeText "${name}-expected.json" (
      builtins.toJSON {
        model = codex.artifacts.model.id;
        context = codex.artifacts.model.contextSize;
      }
    );
  selectedModelsRaw = {
    llama.model.batchSize = 128;
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      vramEstimateMiB = 6144;
      batchSize = 2048;
    };
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      vramEstimateMiB = 4096;
    };
    llama.models."qwen2.5-coder-1.5b-q8-0" = {
      enable = true;
      vramEstimateMiB = 2048;
      contextSize = 4096;
    };
    llama.concurrentModels = true;
    llama.maxLoadedModels = 3;
    llama.memoryBudgetMiB = 12288;
    llama.profiles.coding = {
      model = "qwen2.5-coder-1.5b-q8-0";
      temperature = 0.0;
    };
  };
  selectedModels = ai selectedModelsRaw;
  selectedModelsConfig = import ../modules/ai/interface.nix {
    inherit lib;
    raw = lib.recursiveUpdate aiDefaults selectedModelsRaw;
  };
  selectedModelsArch = import ../platforms/arch/ai {
    inherit lib pkgs;
    config = selectedModelsConfig;
    artifacts = selectedModels.artifacts;
    hardware = host.hardware;
    tailscale = false;
  };
  legacyBaselineConfig = import ../modules/ai/interface.nix {
    inherit lib;
    raw.llama.model.device = "ROCm0";
  };
  legacyBaseline = import ../modules/ai {
    inherit lib;
    config = legacyBaselineConfig;
    skillSources = {
      matt-pocock = inputs.matt-pocock-skills;
      vercel = inputs.vercel-skills;
    };
  };
  legacyBaselineArch = import ../platforms/arch/ai {
    inherit lib pkgs;
    config = legacyBaselineConfig;
    artifacts = legacyBaseline.artifacts;
    hardware = host.hardware;
    tailscale = false;
  };
  preserveOverride = ai {
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      preserveThinking = true;
    };
    llama.profiles.coding.preserveThinking = false;
  };
  disabled = ai { enable = false; };
  v = virtualization {
    enable = true;
    kvm.gui.enable = false;
  };
  gui = virtualization {
    enable = true;
    kvm.gui.enable = true;
  };
  host =
    (import ../lib/eval-configuration.nix {
      inherit lib;
      modules = [ ./fixtures/configuration.nix ];
    }).host;
  home = (import ../lib/mk-home-configuration.nix { inherit inputs; }) {
    inherit (host)
      system
      platform
      hardware
      ai
      ;
    hostName = host.name;
    username = host.deployment.username;
    user = host.users.${host.deployment.username};
  };
  homeDisabled = (import ../lib/mk-home-configuration.nix { inherit inputs; }) {
    inherit (host) system platform hardware;
    ai.enable = false;
    hostName = host.name;
    username = host.deployment.username;
    user = host.users.${host.deployment.username};
  };
  skillRegistry = import ../modules/ai/skills.nix {
    inherit lib;
    skillSources = {
      matt-pocock = inputs.matt-pocock-skills;
      vercel = inputs.vercel-skills;
    };
  };
  unknownSkillSelection = builtins.tryEval (skillRegistry.resolve "not-registered");
  missingSkillRegistry = import ../modules/ai/skills.nix {
    inherit lib;
    skillSources = {
      matt-pocock = inputs.nixpkgs.outPath;
      vercel = inputs.nixpkgs.outPath;
    };
  };
  missingSkillSource = builtins.tryEval (builtins.deepSeq missingSkillRegistry.selected true);
  agentSkillsOnly = ai {
    enable = true;
    agy.enable = false;
  };
  geminiSkillsOnly = ai {
    enable = true;
    skillsPresets.enable = false;
  };
  skillsDisabledWithoutSources = import ../modules/ai {
    inherit lib;
    config = import ../modules/ai/interface.nix {
      inherit lib;
      raw = lib.recursiveUpdate aiDefaults {
        enable = true;
        skillsPresets.enable = false;
        agy.skills.enable = false;
        codex.localProfile.enable = false;
      };
    };
  };
  native = import ../platforms/arch/packages.nix {
    inherit lib;
    inherit (host) hardware;
    modulePackages = v.requiredPackages;
    moduleAurPackages = enabled.aurPackages;
  };
  upstreamSkill = builtins.head (builtins.attrNames skillRegistry.roots);
  skills = lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) home.config.home.file;
  geminiSkills = lib.filterAttrs (
    name: _: lib.hasPrefix ".gemini/config/skills/" name
  ) home.config.home.file;
in
assert
  enabled.aurPackages == [
    "openai-codex-bin"
    "antigravity-cli"
  ];
assert disabled.aurPackages == [ ] && disabled.homeModule.home.file == { };
assert
  home.config.home.file.".codex/llama-cpp.config.toml".text
  == codexProfile.homeModule.home.file.".codex/llama-cpp.config.toml".text;
assert !(home.config.home.file ? ".codex/config.toml");
assert lib.all (
  name: home.config.home.file.".agents/skills/${name}".source == skillRegistry.roots.${name}
) (builtins.attrNames skillRegistry.roots);
assert lib.all (
  name:
  home.config.home.file.".agents/skills/${name}".source == skillRegistry.agentCustomRoots.${name}
  &&
    home.config.home.file.".gemini/config/skills/${name}".source
    == skillRegistry.geminiCustomRoots.${name}
) skillRegistry.custom;
assert !unknownSkillSelection.success;
assert !missingSkillSource.success;
assert agentSkillsOnly.homeModule.home.file ? ".agents/skills/${upstreamSkill}";
assert !(agentSkillsOnly.homeModule.home.file ? ".gemini/config/skills/${upstreamSkill}");
assert geminiSkillsOnly.homeModule.home.file ? ".gemini/config/skills/${upstreamSkill}";
assert !(geminiSkillsOnly.homeModule.home.file ? ".agents/skills/${upstreamSkill}");
assert skillsDisabledWithoutSources.homeModule.home.file == { };
assert !(codexProfileOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert !(codexOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert !(llamaOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert
  (ai {
    enable = true;
    codex.enable = false;
  }).aurPackages == [ "antigravity-cli" ];
assert
  (ai {
    enable = true;
    agy.pkg.enable = false;
  }).aurPackages == [ "openai-codex-bin" ];
assert
  (ai {
    enable = true;
    codex.enable = false;
    agy.pkg.enable = false;
  }).aurPackages == [ ];
assert
  (ai {
    enable = true;
    skillsPresets.enable = false;
    agy.skills.enable = false;
    codex.localProfile.enable = false;
  }).homeModule.home.file == { };
assert (virtualization { }).requiredPackages != [ ];
assert (virtualization { enable = false; }).loginGroups == [ ];
assert builtins.elem "qemu-desktop" v.requiredPackages;
assert builtins.elem "podman" v.requiredPackages;
assert v.loginGroups == [ "kvm" ];
assert v.systemUnits == [ ];
assert !(builtins.elem "virt-manager" v.requiredPackages);
assert builtins.elem "virt-manager" gui.requiredPackages;
assert builtins.elem "libvirt" gui.requiredPackages;
assert gui.systemUnits == [ "libvirtd.socket" ];
assert gui.loginGroups == [ "kvm" ];
assert lib.all
  (
    raw:
    let
      disabledGui = virtualization raw;
    in
    disabledGui.systemUnits == [ ]
    && !(builtins.elem "virt-manager" disabledGui.requiredPackages)
    && !(builtins.elem "libvirt" disabledGui.requiredPackages)
  )
  [
    {
      enable = false;
      kvm.gui.enable = true;
    }
    {
      enable = true;
      kvm.enable = false;
      kvm.gui.enable = true;
    }
    {
      enable = true;
      kvm.gui.enable = false;
    }
  ];
assert !(valid "virtualization" { kvm.gui.enable = "true"; });
assert !(valid "virtualization" { kvm.gui.enabel = true; });
assert
  !(builtins.elem "podman"
    (virtualization {
      enable = true;
      podman.enable = false;
    }).requiredPackages
  );
assert
  (virtualization {
    enable = true;
    kvm.enable = false;
  }).loginGroups == [ ];
assert
  !(builtins.elem "qemu-desktop"
    (virtualization {
      enable = true;
      kvm.enable = false;
    }).requiredPackages
  );
assert lib.all (name: !(valid name { enable = "true"; }) && !(valid name { typo = true; })) [
  "ai"
  "virtualization"
];
assert !(valid "ai" { codex.enabel = true; });
assert !(valid "ai" { codex.localProfile.enable = "true"; });
assert !(valid "ai" { agy.enabel = true; });
assert !(valid "ai" { llama.proxy.httpsPort = 0; });
assert !(valid "ai" { llama.model.microBatchSize = 4096; });
assert !(valid "ai" { llama.model.name = "unknown"; });
assert !(valid "ai" { llama.models.unknown.enable = true; });
assert
  !(valid "ai" {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      vramEstimateMiB = 4096;
    };
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      vramEstimateMiB = 6144;
    };
    llama.models."qwen2.5-coder-1.5b-q8-0" = {
      enable = true;
      vramEstimateMiB = 2048;
    };
    llama.concurrentModels = true;
    llama.maxLoadedModels = 2;
  });
assert
  !(valid "ai" {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      vramEstimateMiB = 4096;
    };
    llama.models."qwen2.5-coder-1.5b-q8-0" = {
      enable = true;
      vramEstimateMiB = 2048;
    };
    llama.concurrentModels = true;
    llama.maxLoadedModels = 2;
    llama.memoryBudgetMiB = 6143;
    llama.model.name = "qwen3.5-4b-q4-k-m";
  });
assert
  !(valid "ai" {
    llama.models."qwen3.5-4b-q4-k-m".enable = true;
    llama.models."qwen2.5-coder-1.5b-q8-0".enable = true;
    llama.concurrentModels = true;
    llama.maxLoadedModels = 2;
  });
assert
  !(valid "ai" {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      vramEstimateMiB = 4096;
    };
    llama.models."qwen2.5-coder-1.5b-q8-0".enable = true;
    llama.concurrentModels = true;
    llama.maxLoadedModels = 2;
    llama.memoryBudgetMiB = 6144;
    llama.model.name = "qwen3.5-4b-q4-k-m";
  });
assert
  !(valid "ai" {
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      preserveThinking = true;
    };
    llama.profiles.coding.enableThinking = true;
  });
assert valid "ai" {
  llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
    enable = true;
    preserveThinking = true;
  };
  llama.profiles.coding = {
    enableThinking = true;
    preserveThinking = false;
  };
};
assert
  !(valid "ai" {
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      enableThinking = true;
      preserveThinking = true;
    };
  });
assert
  !(valid "ai" {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      batchSize = 128;
    };
    llama.model.name = "qwen3.5-4b-q4-k-m";
  });
assert
  !(valid "ai" {
    llama.concurrentModels = false;
    llama.maxLoadedModels = 2;
  });
assert !(valid "ai" { llama.source.revision = "main"; });
assert
  !(valid "ai" {
    llama.profiles.invalid = {
      enableThinking = true;
      preserveThinking = true;
    };
  });
assert !(valid "virtualization" { kvm.enabel = true; });
assert builtins.elem "openai-codex-bin" native.aur;
assert builtins.elem "antigravity-cli" native.aur;
assert enabled.artifacts.model.contextSize == 4096;
assert profiled.artifacts.profiles.coding.artifacts.temperature == 0.6;
assert
  builtins.attrNames selectedModels.artifacts.models == [
    "qwen2.5-coder-1.5b-q8-0"
    "qwen3.5-4b-q4-k-m"
    "qwen3.6-35b-a3b-ud-q5-k-m"
  ];
assert selectedModels.artifacts.server.modelsMax == 3;
assert selectedModels.artifacts.concurrentModels;
assert selectedModels.artifacts.profiles.default.model == "qwen3.6-35b-a3b-ud-q5-k-m";
assert selectedModels.artifacts.profiles.coding.model == "qwen2.5-coder-1.5b-q8-0";
assert selectedModels.artifacts.models."qwen2.5-coder-1.5b-q8-0".contextSize == 4096;
assert selectedModels.artifacts.model.batchSize == 2048;
assert selectedModels.artifacts.model.microBatchSize == 512;
assert preserveOverride.artifacts.profiles.coding.artifacts.enableThinking == null;
assert preserveOverride.artifacts.profiles.coding.artifacts.preserveThinking == false;
assert !(builtins.elem "llama-cpp" native.pacman);
assert !(builtins.elem "caddy" native.pacman);
assert builtins.elem "qemu-desktop" native.pacman && builtins.elem "podman" native.pacman;
assert
  lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) homeDisabled.config.home.file
  == { };
assert
  lib.filterAttrs (name: _: lib.hasPrefix ".gemini/config/skills/" name) homeDisabled.config.home.file
  == { };
assert skills != { };
assert lib.all (file: !file.recursive) (builtins.attrValues skills);
assert geminiSkills != { };
assert lib.all (file: !file.recursive) (builtins.attrValues geminiSkills);
pkgs.runCommand "capabilities-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    python3 - ${selectedModelsArch.manifest} \
      ${codexProfileText "codex-default" codexProfile} \
      ${codexProfileExpected "codex-default" codexProfile} \
      ${codexProfileText "codex-selected" selectedCodexProfile} \
      ${codexProfileExpected "codex-selected" selectedCodexProfile} \
      ${legacyBaselineArch.manifest} <<'PY'
  import json
  import sys
  import tomllib

  def check_codex_profile(toml_path, expected_path):
      with open(toml_path, "rb") as source:
          profile = tomllib.load(source)
      with open(expected_path, encoding="utf-8") as source:
          expected = json.load(source)

      assert profile["model"] == expected["model"]
      assert profile["model_context_window"] == expected["context"]
      assert profile["model_auto_compact_token_limit"] == expected["context"] * 3 // 4
      provider = profile["model_providers"][profile["model_provider"]]
      assert provider["base_url"].startswith("http://127.0.0.1:")

  check_codex_profile(sys.argv[2], sys.argv[3])
  check_codex_profile(sys.argv[4], sys.argv[5])

  manifest = json.load(open(sys.argv[1], encoding="utf-8"))
  baseline = json.load(open(sys.argv[6], encoding="utf-8"))
  for field in ("legacyPreset", "legacyDropin"):
      assert manifest["generated"][field] == baseline["generated"][field], (
          "legacy ownership recognition must not change with selected models or overrides", field
      )
  router = json.loads(manifest["generated"]["switcherConfig"])
  models = router["models"]
  assert router["globalTTL"] == 0
  assert router["groups"]["default"]["swap"] is False
  assert router["groups"]["default"]["exclusive"] is False
  assert router["groups"]["default"]["persistent"] is True
  assert len(models) == 3
  assert set(router["groups"]["default"]["members"]) == set(models)
  for key, model in models.items():
      if key.startswith("Qwen3.6"):
          continue
      assert "--fit off" in model["cmd"]
      assert "--n-gpu-layers 99" in model["cmd"]
      assert "--n-cpu-moe 0" in model["cmd"]
  assert any("qwen2.5-coder" in key.lower() for key in models)
  qwen = next(model for key, model in models.items() if key.startswith("Qwen3.6"))
  assert "--batch-size 2048" in qwen["cmd"]
  assert "--ubatch-size 512" in qwen["cmd"]
  PY
    touch $out
''
