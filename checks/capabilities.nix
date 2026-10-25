{
  lib,
  pkgs,
  inputs,
}:
let
  aiDefaults = {
    llama = {
      enable = true;
      model = {
        name = "qwen3.6-35b-a3b-mxfp4-moe";
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
        obsidian = inputs.obsidian-skills;
        vercel = inputs.vercel-skills;
      };
    };
  evaluate =
    extra:
    import ../lib/eval-configuration.nix {
      inherit lib;
      modules = [
        ./fixtures/configuration.nix
        extra
      ];
    };
  archFor = extra: (evaluate extra).config.arch;
  virtualization = raw: archFor { virtualization = raw; };
  validConfig = module: (builtins.tryEval (builtins.deepSeq (evaluate module).host true)).success;
  validAi =
    raw:
    (builtins.tryEval (
      builtins.deepSeq (import ../modules/ai/interface.nix {
        inherit lib;
        raw = lib.recursiveUpdate aiDefaults raw;
      }) true
    )).success;
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
  selectedModelsRaw = {
    llama.model.batchSize = 128;
    llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
      enable = true;
      vramEstimateMiB = 6144;
      batchSize = 384;
      microBatchSize = 96;
      threads = 3;
      threadsBatch = 5;
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
    llama.vramLimitsMiB."drm/0000:03:00.0/vram" = 173;
    llama.profiles.instruct.temperature = 0.42;
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
    tailscale = false;
  };
  exclusiveModelsRaw = {
    llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
      enable = true;
      vramEstimateMiB = 173;
    };
    llama.models."qwen2.5-coder-1.5b-q8-0" = {
      enable = true;
      vramEstimateMiB = 181;
    };
    llama.memoryBudgetMiB = 200;
    llama.profiles.thinking-general.model = "qwen2.5-coder-1.5b-q8-0";
  };
  exclusiveModels = ai exclusiveModelsRaw;
  exclusiveModelsConfig = import ../modules/ai/interface.nix {
    inherit lib;
    raw = lib.recursiveUpdate aiDefaults exclusiveModelsRaw;
  };
  exclusiveModelsArch = import ../platforms/arch/ai {
    inherit lib pkgs;
    config = exclusiveModelsConfig;
    artifacts = exclusiveModels.artifacts;
    tailscale = false;
  };
  preserveOverride = ai {
    llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
      enable = true;
      preserveThinking = true;
    };
    llama.profiles.coding.preserveThinking = false;
  };
  disabled = ai { enable = false; };
  baseline = archFor { };
  v = virtualization {
    enable = true;
    kvm.gui.enable = false;
  };
  gui = virtualization {
    enable = true;
    kvm.gui.enable = true;
  };
  fixtures = import ./lib.nix { inherit inputs lib; };
  home = fixtures.home [ ] "fixture";
  homeDisabled = fixtures.home [ { programs.ai.enable = false; } ] "fixture";
  skillRegistry = import ../modules/ai/skills.nix {
    inherit lib;
    skillSources = {
      matt-pocock = inputs.matt-pocock-skills;
      obsidian = inputs.obsidian-skills;
      vercel = inputs.vercel-skills;
    };
  };
  unknownSkillSelection = builtins.tryEval (skillRegistry.resolve "not-registered");
  missingSkillRegistry = import ../modules/ai/skills.nix {
    inherit lib;
    skillSources = {
      matt-pocock = inputs.nixpkgs.outPath;
      obsidian = inputs.nixpkgs.outPath;
      vercel = inputs.nixpkgs.outPath;
    };
  };
  missingSkillSource = builtins.tryEval (builtins.deepSeq missingSkillRegistry.selected true);
  agentSkillsOnly = ai {
    enable = true;
    claude.skills.enable = false;
  };
  claudeSkillsOnly = ai {
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
        claude.skills.enable = false;
        codex.localProfile.enable = false;
      };
    };
  };
  upstreamSkill = builtins.head (builtins.attrNames skillRegistry.roots);
in
assert disabled.homeModule.home.file == { };
assert !(home.config.home.file ? ".codex/config.toml");
assert !unknownSkillSelection.success;
assert !missingSkillSource.success;
assert agentSkillsOnly.homeModule.home.file ? ".agents/skills/${upstreamSkill}";
assert !(agentSkillsOnly.homeModule.home.file ? ".claude/skills/${upstreamSkill}");
assert claudeSkillsOnly.homeModule.home.file ? ".claude/skills/${upstreamSkill}";
assert !(claudeSkillsOnly.homeModule.home.file ? ".agents/skills/${upstreamSkill}");
assert skillsDisabledWithoutSources.homeModule.home.file == { };
assert !(codexProfileOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert !(codexOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert !(llamaOff.homeModule.home.file ? ".codex/llama-cpp.config.toml");
assert
  (ai {
    enable = true;
    skillsPresets.enable = false;
    claude.skills.enable = false;
    codex.localProfile.enable = false;
  }).homeModule.home.file == { };
assert
  let
    extra = archFor {
      packages.extra = {
        pacman = [ "fixture-repo-app" ];
        aur = [ "fixture-aur-app" ];
      };
    };
  in
  builtins.elem "fixture-repo-app" extra.pacman && builtins.elem "fixture-aur-app" extra.aur;
assert !(builtins.elem "kvm" (virtualization { enable = false; }).groups);
assert builtins.elem "kvm" v.groups;
assert !(builtins.elem "libvirtd.socket" v.systemUnits);
assert builtins.elem "libvirtd.socket" gui.systemUnits && builtins.elem "kvm" gui.groups;
assert lib.all
  (
    raw:
    let
      disabledGui = virtualization raw;
    in
    !(builtins.elem "libvirtd.socket" disabledGui.systemUnits)
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
assert
  let
    noKvm = virtualization {
      enable = true;
      kvm.enable = false;
    };
  in
  !(builtins.elem "kvm" noKvm.groups);
assert lib.all (module: !(validConfig module)) [
  { virtualization.kvm.gui.enable = "true"; }
  { virtualization.kvm.gui.enabel = true; }
  { virtualization.kvm.enabel = true; }
  { virtualization.enable = "true"; }
  { virtualization.typo = true; }
];
assert !(validAi { enable = "true"; }) && !(validAi { typo = true; });
assert !(validAi { codex.enabel = true; });
assert !(validAi { codex.localProfile.enable = "true"; });
assert !(validAi { claude.enabel = true; });
assert !(validAi { llama.proxy.httpsPort = 0; });
assert !(validAi { llama.vramLimitsMiB.invalid = 173; });
assert !(validAi { llama.model.microBatchSize = 4096; });
assert !(validAi { llama.model.name = "unknown"; });
assert !(validAi { llama.models.unknown.enable = true; });
assert
  !(validAi {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      vramEstimateMiB = 4096;
    };
    llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
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
  !(validAi {
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
  !(validAi {
    llama.models."qwen3.5-4b-q4-k-m".enable = true;
    llama.models."qwen2.5-coder-1.5b-q8-0".enable = true;
    llama.concurrentModels = true;
    llama.maxLoadedModels = 2;
  });
assert
  !(validAi {
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
assert validAi {
  llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
    enable = true;
    preserveThinking = true;
  };
  llama.profiles.coding.enableThinking = true;
};
assert validAi {
  llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
    enable = true;
    preserveThinking = true;
  };
  llama.profiles.coding = {
    enableThinking = true;
    preserveThinking = false;
  };
};
assert validAi {
  llama.models."qwen3.6-35b-a3b-mxfp4-moe" = {
    enable = true;
    enableThinking = true;
    preserveThinking = true;
  };
};
assert
  !(validAi {
    llama.models."qwen3.5-4b-q4-k-m" = {
      enable = true;
      batchSize = 128;
    };
    llama.model.name = "qwen3.5-4b-q4-k-m";
  });
assert
  !(validAi {
    llama.concurrentModels = false;
    llama.maxLoadedModels = 2;
  });
assert !(validAi { llama.source.revision = "main"; });
assert
  !(validAi (
    lib.recursiveUpdate exclusiveModelsRaw {
      llama.memoryBudgetMiB = 180;
    }
  ));
assert
  !(validAi {
    llama.model.name = "qwen3.5-9b-q4-k-m";
    llama.profiles.invalid = {
      enableThinking = true;
      preserveThinking = true;
    };
  });
assert
  builtins.attrNames selectedModels.artifacts.models == [
    "qwen2.5-coder-1.5b-q8-0"
    "qwen3.5-4b-q4-k-m"
    "qwen3.6-35b-a3b-mxfp4-moe"
  ];
assert selectedModels.artifacts.concurrentModels;
assert selectedModels.artifacts.profiles.default.model == "qwen3.6-35b-a3b-mxfp4-moe";
assert selectedModels.artifacts.profiles.coding.model == "qwen2.5-coder-1.5b-q8-0";
assert selectedModels.artifacts.models."qwen2.5-coder-1.5b-q8-0".contextSize == 4096;
assert selectedModels.artifacts.model.batchSize == 384;
assert preserveOverride.artifacts.profiles.coding.artifacts.enableThinking == true;
assert preserveOverride.artifacts.profiles.coding.artifacts.preserveThinking == false;
# Prepared llama.cpp binaries and Caddy stay outside the declared inventory.
assert !(builtins.elem "llama-cpp" baseline.pacman) && !(builtins.elem "caddy" baseline.pacman);
assert
  lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) homeDisabled.config.home.file
  == { };
pkgs.runCommand "capabilities-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    python ${../platforms/arch/ai/tests/test_generated.py} \
      ${selectedModelsArch.manifest} ${pkgs.llama-swap}/bin/llama-swap \
      ${../modules/ai/tests/test_router.py} \
      ${pkgs.writeText "routing-expectations.json" (
        builtins.toJSON {
          baselineId = selectedModels.artifacts.models."qwen3.6-35b-a3b-mxfp4-moe".id;
          batch = selectedModelsRaw.llama.models."qwen3.6-35b-a3b-mxfp4-moe".batchSize;
          microBatch = selectedModelsRaw.llama.models."qwen3.6-35b-a3b-mxfp4-moe".microBatchSize;
          concurrent = selectedModelsRaw.llama.concurrentModels;
          exclusiveManifest = exclusiveModelsArch.manifest;
          exclusiveDefaultId = exclusiveModels.artifacts.models."qwen3.6-35b-a3b-mxfp4-moe".id;
          exclusiveTargetId = exclusiveModels.artifacts.models."qwen2.5-coder-1.5b-q8-0".id;
        }
      )}
    python - ${codexProfileText "codex-default" codexProfile} \
      ${codexProfileText "codex-selected" selectedCodexProfile} <<'PY'
  import sys
  import tomllib
  from urllib.parse import urlsplit

  for filename in sys.argv[1:]:
      with open(filename, "rb") as source:
          profile = tomllib.load(source)
      provider = profile["model_providers"][profile["model_provider"]]
      endpoint = urlsplit(provider["base_url"])
      assert endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
      assert endpoint.path == "/v1" and endpoint.port
      assert provider["wire_api"] == "responses"
  PY
    touch $out
''
