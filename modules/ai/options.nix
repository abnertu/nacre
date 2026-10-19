{ lib }:
let
  inventory = import ./artifacts.nix;
  enable = description: (lib.mkEnableOption description) // { default = true; };
  port = lib.types.ints.between 1 65535;
  nullable = type: lib.types.nullOr type;
  positive = nullable lib.types.ints.positive;
  runtimeOptions = {
    device = lib.mkOption {
      type = nullable (lib.types.strMatching "(ROCm|Vulkan)[0-9]+");
      default = null;
    };
    contextSize = lib.mkOption {
      type = positive;
      default = null;
    };
    fit = lib.mkOption {
      type = nullable lib.types.bool;
      default = null;
    };
    fitTarget = lib.mkOption {
      type = positive;
      default = null;
    };
    gpuLayers = lib.mkOption {
      type = nullable (lib.types.ints.between 0 100000);
      default = null;
    };
    cpuMoeLayers = lib.mkOption {
      type = nullable (lib.types.ints.between 0 100000);
      default = null;
    };
    cacheTypeK = lib.mkOption {
      type = nullable (
        lib.types.enum [
          "f16"
          "q8_0"
          "q4_0"
        ]
      );
      default = null;
    };
    cacheTypeV = lib.mkOption {
      type = nullable (
        lib.types.enum [
          "f16"
          "q8_0"
          "q4_0"
        ]
      );
      default = null;
    };
    batchSize = lib.mkOption {
      type = positive;
      default = null;
    };
    microBatchSize = lib.mkOption {
      type = positive;
      default = null;
    };
    parallel = lib.mkOption {
      type = positive;
      default = null;
    };
  };
  samplingOptions = {
    reasoningEffort = lib.mkOption {
      type = nullable (
        lib.types.enum [
          "minimal"
          "low"
          "medium"
          "high"
          "xhigh"
        ]
      );
      default = null;
    };
    enableThinking = lib.mkOption {
      type = nullable lib.types.bool;
      default = null;
    };
    preserveThinking = lib.mkOption {
      type = nullable lib.types.bool;
      default = null;
    };
    temperature = lib.mkOption {
      type = nullable lib.types.float;
      default = null;
    };
    topP = lib.mkOption {
      type = nullable lib.types.float;
      default = null;
    };
    topK = lib.mkOption {
      type = nullable (lib.types.ints.between 0 100000);
      default = null;
    };
    minP = lib.mkOption {
      type = nullable lib.types.float;
      default = null;
    };
    presencePenalty = lib.mkOption {
      type = nullable lib.types.float;
      default = null;
    };
    repetitionPenalty = lib.mkOption {
      type = nullable lib.types.float;
      default = null;
    };
  };
in
{
  enable = enable "ai";
  codex = {
    enable = enable "Codex";
    localProfile.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Manage a Codex profile for the selected local llama.cpp model.";
    };
  };
  skillsPresets.enable = enable "the registered Codex agent skill presets";
  claude = {
    enable = enable "Claude Code";
    skills.enable = enable "the registered agent skills in ~/.claude/skills";
  };
  # Graphical: installed only with the desktop.
  claudeDesktop.enable = enable "Claude Desktop";
  llama = {
    enable = lib.mkEnableOption "llama.cpp on a local GPU";
    maxLoadedModels = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1;
    };
    memoryBudgetMiB = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
    };
    concurrentModels = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };
    models = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule (
          { name, ... }: {
            options = {
              enable = lib.mkOption {
                type = lib.types.bool;
                default = name == inventory.defaultModel;
              };
              vramEstimateMiB = lib.mkOption {
                type = lib.types.nullOr lib.types.ints.positive;
                default = null;
              };
            }
            // runtimeOptions
            // samplingOptions;
          }
        )
      );
      default = { };
    };
    model = {
      name = lib.mkOption {
        type = lib.types.enum (builtins.attrNames inventory.models);
        default = inventory.defaultModel;
      };
      device = lib.mkOption {
        type = lib.types.nullOr (lib.types.strMatching "(ROCm|Vulkan)[0-9]+");
        default = null;
      };
      contextSize = lib.mkOption {
        type = lib.types.nullOr lib.types.ints.positive;
        default = null;
      };
      fitTarget = lib.mkOption {
        type = lib.types.nullOr lib.types.ints.positive;
        default = null;
      };
      fit = lib.mkOption {
        type = lib.types.nullOr lib.types.bool;
        default = null;
      };
      gpuLayers = lib.mkOption {
        type = lib.types.nullOr (lib.types.ints.between 0 100000);
        default = null;
      };
      cpuMoeLayers = lib.mkOption {
        type = lib.types.nullOr (lib.types.ints.between 0 100000);
        default = null;
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
      };
      batchSize = lib.mkOption {
        type = lib.types.nullOr lib.types.ints.positive;
        default = null;
      };
      microBatchSize = lib.mkOption {
        type = lib.types.nullOr lib.types.ints.positive;
        default = null;
      };
      parallel = lib.mkOption {
        type = lib.types.nullOr lib.types.ints.positive;
        default = null;
      };
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
      };
      enableThinking = lib.mkOption {
        type = lib.types.nullOr lib.types.bool;
        default = null;
      };
      preserveThinking = lib.mkOption {
        type = lib.types.nullOr lib.types.bool;
        default = null;
      };
      temperature = lib.mkOption {
        type = lib.types.nullOr lib.types.float;
        default = null;
      };
      topP = lib.mkOption {
        type = lib.types.nullOr lib.types.float;
        default = null;
      };
      topK = lib.mkOption {
        type = lib.types.nullOr (lib.types.ints.between 0 100000);
        default = null;
      };
      minP = lib.mkOption {
        type = lib.types.nullOr lib.types.float;
        default = null;
      };
      presencePenalty = lib.mkOption {
        type = lib.types.nullOr lib.types.float;
        default = null;
      };
      repetitionPenalty = lib.mkOption {
        type = lib.types.nullOr lib.types.float;
        default = null;
      };
    };
    profiles = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            model = lib.mkOption {
              type = lib.types.nullOr (lib.types.enum (builtins.attrNames inventory.models));
              default = null;
            };
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
            };
            enableThinking = lib.mkOption {
              type = lib.types.nullOr lib.types.bool;
              default = null;
            };
            preserveThinking = lib.mkOption {
              type = lib.types.nullOr lib.types.bool;
              default = null;
            };
            temperature = lib.mkOption {
              type = lib.types.nullOr lib.types.float;
              default = null;
            };
            topP = lib.mkOption {
              type = lib.types.nullOr lib.types.float;
              default = null;
            };
            topK = lib.mkOption {
              type = lib.types.nullOr (lib.types.ints.between 0 100000);
              default = null;
            };
            minP = lib.mkOption {
              type = lib.types.nullOr lib.types.float;
              default = null;
            };
            presencePenalty = lib.mkOption {
              type = lib.types.nullOr lib.types.float;
              default = null;
            };
            repetitionPenalty = lib.mkOption {
              type = lib.types.nullOr lib.types.float;
              default = null;
            };
          }
          // samplingOptions;
        }
      );
      default = { };
    };
    proxy = {
      enable = enable "the Caddy and Tailscale Serve proxy for llama.cpp";
      httpsPort = lib.mkOption {
        type = port;
        default = 443;
      };
    };
  };
}
