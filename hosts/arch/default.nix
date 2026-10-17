{ config, lib, ... }:
{
  imports = [ ./system.nix ];
  networking.hostname.name = lib.mkDefault "arch";
  deployment.username = lib.mkDefault "abnertu";
  hardware = lib.mapAttrsRecursive (_: lib.mkDefault) (import ./hardware.nix);
  programs.ai.llama = lib.mapAttrsRecursive (_: lib.mkDefault) {
    enable = true;
    model = {
      name = "qwen3.5-4b-q4-k-m";
      device = "Vulkan0";
    };
    concurrentModels = true;
    maxLoadedModels = 2;
    memoryBudgetMiB = 11264;
    models = {
      "qwen3.5-4b-q4-k-m" = {
        enable = true;
        vramEstimateMiB = 6144;
      };
      "qwen2.5-coder-3b-q4-k-m" = {
        enable = true;
        vramEstimateMiB = 3072;
      };
    };
    profiles = {
      "thinking-general" = {
        enableThinking = true;
        temperature = 1.0;
        topP = 0.95;
        topK = 20;
        minP = 0.0;
        presencePenalty = 0.0;
        repetitionPenalty = 1.0;
      };
      "thinking-coding" = {
        enableThinking = true;
        temperature = 0.6;
        topP = 0.95;
        topK = 20;
        minP = 0.0;
        presencePenalty = 0.0;
        repetitionPenalty = 1.0;
      };
      instruct = {
        enableThinking = false;
        temperature = 0.7;
        topP = 0.8;
        topK = 20;
        minP = 0.0;
        presencePenalty = 1.5;
        repetitionPenalty = 1.0;
      };
      "preserved-thinking" = {
        preserveThinking = true;
        temperature = 0.6;
        topP = 0.95;
        topK = 20;
        minP = 0.0;
        presencePenalty = 0.0;
        repetitionPenalty = 1.0;
      };
    };
  };
  users.users = import ./users.nix { inherit config lib; };
  services.gitlabRunner.configFiles = lib.mkDefault [
    ./runners/frontend.toml
    ./runners/dotnet.toml
  ];
  services.personalAgent.enable = lib.mkDefault true;
  services.powerpanel.enable = lib.mkDefault true;
}
