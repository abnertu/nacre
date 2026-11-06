# Typed AI tool, model, profile, preparation and skill-set policy.
{ lib }:
let
  inventory = import ./artifacts.nix;
  # An enable option that defaults to true.
  enabledByDefault =
    description:
    lib.mkEnableOption description
    // {
      default = true;
    };
  port = lib.types.ints.between 1 65535;
  optionalPositive = lib.types.nullOr lib.types.ints.positive;
  runtimeOptions = {
    device = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "(ROCm|Vulkan)[0-9]+");
      default = null;
      description = "llama.cpp device, such as Vulkan0 or ROCm0; null uses the llama.cpp default.";
    };
    contextSize = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "Context length in tokens; null uses the model's runtime default.";
    };
    fit = lib.mkOption {
      type = lib.types.nullOr lib.types.bool;
      default = null;
      description = "Whether llama.cpp fits offload and context to free memory; false keeps the fixed values.";
    };
    fitTarget = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "Free memory, in MiB, that fitting leaves on the device; null uses the llama.cpp default.";
    };
    gpuLayers = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 0 100000);
      default = null;
      description = "Layers offloaded to the GPU; null uses the model's runtime default.";
    };
    cpuMoeLayers = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 0 100000);
      default = null;
      description = "Mixture-of-experts layers kept on the CPU; null uses the model's runtime default.";
    };
    cacheTypeK = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "f16"
          "q8_0"
          "q4_0"
        ]
      );
      default = null;
      description = "KV cache type of the keys; null uses the model's runtime default.";
    };
    cacheTypeV = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "f16"
          "q8_0"
          "q4_0"
        ]
      );
      default = null;
      description = "KV cache type of the values; null uses the model's runtime default.";
    };
    batchSize = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "Logical batch size for prompt processing; null uses the model's runtime default.";
    };
    microBatchSize = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "Physical micro-batch size; null uses the model's runtime default.";
    };
    parallel = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "Concurrent request slots of the backend; null uses the model's runtime default.";
    };
    threads = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "CPU threads for generation; null uses the native default.";
    };
    threadsBatch = lib.mkOption {
      type = optionalPositive;
      default = null;
      description = "CPU threads for prompt processing; null uses the native default.";
    };
  };
  samplingOptions = {
    reasoningEffort = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "minimal"
          "low"
          "medium"
          "high"
          "xhigh"
        ]
      );
      default = null;
      description = "Reasoning effort sent to the chat template; null uses the model default.";
    };
    enableThinking = lib.mkOption {
      type = lib.types.nullOr lib.types.bool;
      default = null;
      description = "Whether the model starts new reasoning; null uses the model default.";
    };
    preserveThinking = lib.mkOption {
      type = lib.types.nullOr lib.types.bool;
      default = null;
      description = "Whether earlier-turn reasoning stays in the prompt, where the template supports it; null uses the model default.";
    };
    temperature = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Sampling temperature; null uses the model default.";
    };
    topP = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Nucleus sampling probability; null uses the model default.";
    };
    topK = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 0 100000);
      default = null;
      description = "Top-k sampling limit; null uses the model default.";
    };
    minP = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Minimum token probability relative to the best token; null uses the model default.";
    };
    presencePenalty = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Penalty for tokens already present; null uses the model default.";
    };
    repetitionPenalty = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Penalty for repeated tokens; null uses the model default.";
    };
  };
in
{
  enable = enabledByDefault "the AI tools";
  codex = {
    enable = enabledByDefault "Codex";
    localProfile.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Manage a Codex profile for the selected local llama.cpp model.";
    };
  };
  skills = {
    enable = enabledByDefault "managed agent skills";
    agents.enable = enabledByDefault "the selected agent skills in ~/.agents/skills";
    claude.enable = enabledByDefault "the selected agent skills in ~/.claude/skills";
    builtins = {
      mattpocock.enable = enabledByDefault "the built-in Matt Pocock skill bundle";
      obsidian.enable = enabledByDefault "the built-in Obsidian skill bundle";
      vercel.enable = enabledByDefault "the built-in Vercel skill bundle";
      abnertu.enable = enabledByDefault "the built-in abnertu skill bundle";
      gh.enable = enabledByDefault "the gh and gh-skill skills from the packaged GitHub CLI source";
    };
    exclude = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "loop-me" ];
      description = "Skill names omitted from both targets; unmatched names are ignored, including names from disabled bundles.";
    };
    sets = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            enable = enabledByDefault "this custom agent skill set";
            source = lib.mkOption {
              type = lib.types.path;
              description = "Source tree of the set, such as a flake input.";
            };
            skills = lib.mkOption {
              type = lib.types.attrsOf (lib.types.strMatching "[^/].*");
              example = {
                tdd = "skills/engineering/tdd";
              };
              description = "Skills of the set: each name and its directory inside the source, which holds a SKILL.md.";
            };
          };
        }
      );
      default = { };
      example = lib.literalExpression ''
        {
          personal = {
            source = inputs.personal-skills;
            skills.my-skill = "skills/my-skill";
          };
        }
      '';
      description = "Agent skill sets of this machine, keyed by set name; each skill name may appear in one set.";
    };
  };
  claude = {
    enable = enabledByDefault "Claude Code";
  };
  # Graphical: installed only with the desktop.
  claudeDesktop.enable = enabledByDefault "Claude Desktop";
  llama = {
    enable = lib.mkEnableOption "llama.cpp on a local GPU";
    maxLoadedModels = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1;
      description = "Largest number of model backends resident at once; it must be 1 unless concurrentModels is set.";
    };
    memoryBudgetMiB = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "Validate declared model estimates; this does not enforce a runtime limit.";
    };
    vramLimitsMiB = lib.mkOption {
      type = lib.types.addCheck (lib.types.attrsOf lib.types.ints.positive) (
        limits:
        lib.all (
          region: builtins.match "drm/[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\\.[0-7]/vram[0-9]*" region != null
        ) (builtins.attrNames limits)
      );
      default = { };
      description = "Enforce per-region dmem.max limits for the router and all model backends.";
    };
    concurrentModels = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether selected models stay resident together, up to maxLoadedModels, instead of swapping on demand.";
    };
    models = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule (
          { name, ... }: {
            options = {
              enable = lib.mkOption {
                type = lib.types.bool;
                default = name == inventory.defaultModel;
                defaultText = lib.literalExpression "name == defaultModel";
                description = "Whether this model is selected, so that preparation fetches it and the router serves it.";
              };
              vramEstimateMiB = lib.mkOption {
                type = lib.types.nullOr lib.types.ints.positive;
                default = null;
                description = "Planned device memory of this model, in MiB, checked against memoryBudgetMiB.";
              };
            }
            // runtimeOptions
            // samplingOptions;
          }
        )
      );
      default = { };
      description = "Per-model settings, keyed by inventory model name; they override llama.model for that model.";
    };
    model = {
      name = lib.mkOption {
        type = lib.types.enum (builtins.attrNames inventory.models);
        default = inventory.defaultModel;
        defaultText = lib.literalExpression "defaultModel";
        description = "The default model, which receives the settings below.";
      };
    }
    // runtimeOptions
    // samplingOptions;
    profiles = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            model = lib.mkOption {
              type = lib.types.nullOr (lib.types.enum (builtins.attrNames inventory.models));
              default = null;
              description = "Selected model that this profile runs on; null uses the default model.";
            };

          }
          // samplingOptions;
        }
      );
      default = { };
      description = "Named sampling profiles that share a model's backend and change only sampling and thinking.";
    };
    proxy = {
      enable = enabledByDefault "the Caddy and Tailscale Serve proxy for llama.cpp";
      httpsPort = lib.mkOption {
        type = port;
        default = 443;
        description = "Tailnet HTTPS port that Tailscale Serve exposes for the proxy.";
      };
    };
  };
}
