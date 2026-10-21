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
  aiAur =
    raw:
    builtins.sort builtins.lessThan (
      lib.intersectLists [
        "claude-code"
        "claude-desktop"
        "openai-codex-bin"
      ] (archFor { programs.ai = raw; }).aur
    );
  validConfig = module: (builtins.tryEval (builtins.deepSeq (evaluate module).host true)).success;
  validAi =
    raw:
    (builtins.tryEval (
      builtins.deepSeq (import ../modules/ai/interface.nix {
        inherit lib;
        raw = lib.recursiveUpdate aiDefaults raw;
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
  skills = lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) home.config.home.file;
in
assert
  aiAur { enable = true; } == [
    "claude-code"
    "claude-desktop"
    "openai-codex-bin"
  ];
assert aiAur { enable = false; } == [ ] && disabled.homeModule.home.file == { };
assert
  home.config.home.file.".codex/llama-cpp.config.toml".text
  == codexProfile.homeModule.home.file.".codex/llama-cpp.config.toml".text;
assert !(home.config.home.file ? ".codex/config.toml");
assert lib.all (
  name: home.config.home.file.".agents/skills/${name}".source == skillRegistry.roots.${name}
) (builtins.attrNames skillRegistry.roots);
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
  aiAur {
    enable = true;
    claude.enable = false;
    claudeDesktop.enable = false;
  } == [ "openai-codex-bin" ];
assert
  aiAur {
    enable = true;
    codex.enable = false;
  } == [
    "claude-code"
    "claude-desktop"
  ];
# Claude Desktop is graphical and follows the desktop.
assert
  !(builtins.elem "claude-desktop"
    (archFor {
      programs.ai.enable = true;
      desktop.enable = false;
    }).aur
  );
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
assert builtins.elem "qemu-desktop" (virtualization { }).pacman;
assert !(builtins.elem "kvm" (virtualization { enable = false; }).groups);
assert builtins.elem "qemu-desktop" v.pacman && builtins.elem "podman" v.pacman;
assert builtins.elem "kvm" v.groups;
assert !(builtins.elem "libvirtd.socket" v.systemUnits);
assert !(builtins.elem "virt-manager" v.pacman);
assert builtins.elem "virt-manager" gui.pacman && builtins.elem "libvirt" gui.pacman;
assert builtins.elem "libvirtd.socket" gui.systemUnits && builtins.elem "kvm" gui.groups;
assert lib.all
  (
    raw:
    let
      disabledGui = virtualization raw;
    in
    !(builtins.elem "libvirtd.socket" disabledGui.systemUnits)
    && !(builtins.elem "virt-manager" disabledGui.pacman)
    && !(builtins.elem "libvirt" disabledGui.pacman)
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
  !(builtins.elem "podman"
    (virtualization {
      enable = true;
      podman.enable = false;
    }).pacman
  );
assert
  let
    noKvm = virtualization {
      enable = true;
      kvm.enable = false;
    };
  in
  !(builtins.elem "kvm" noKvm.groups) && !(builtins.elem "qemu-desktop" noKvm.pacman);
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
assert !(validAi { llama.model.microBatchSize = 4096; });
assert !(validAi { llama.model.name = "unknown"; });
assert !(validAi { llama.models.unknown.enable = true; });
assert
  !(validAi {
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
assert
  !(validAi {
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      preserveThinking = true;
    };
    llama.profiles.coding.enableThinking = true;
  });
assert validAi {
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
  !(validAi {
    llama.models."qwen3.6-35b-a3b-ud-q5-k-m" = {
      enable = true;
      enableThinking = true;
      preserveThinking = true;
    };
  });
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
  !(validAi {
    llama.profiles.invalid = {
      enableThinking = true;
      preserveThinking = true;
    };
  });
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
# Prepared llama.cpp binaries and Caddy stay outside the declared inventory.
assert !(builtins.elem "llama-cpp" baseline.pacman) && !(builtins.elem "caddy" baseline.pacman);
assert
  lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) homeDisabled.config.home.file
  == { };
assert skills != { };
assert lib.all (file: !file.recursive) (builtins.attrValues skills);
pkgs.runCommand "capabilities-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    python3 - ${selectedModelsArch.manifest} \
      ${codexProfileText "codex-default" codexProfile} \
      ${codexProfileExpected "codex-default" codexProfile} \
      ${codexProfileText "codex-selected" selectedCodexProfile} \
      ${codexProfileExpected "codex-selected" selectedCodexProfile} <<'PY'
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
