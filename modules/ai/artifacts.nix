let
  qwenProfile = enableThinking: temperature: topP: presencePenalty: {
    inherit
      enableThinking
      temperature
      topP
      presencePenalty
      ;
    topK = 20;
    minP = 0.0;
    repetitionPenalty = 1.0;
  };
  qwenProfiles = {
    thinking-general = qwenProfile true 1.0 0.95 1.5;
    thinking-coding = qwenProfile true 0.6 0.95 0.0;
    instruct = qwenProfile false 0.7 0.8 1.5;
    preserved-thinking = (qwenProfile true 0.6 0.95 0.0) // {
      preserveThinking = true;
    };
  };
  runtime = {
    contextSize = 32768;
    fit = false;
    fitTarget = 4096;
    gpuLayers = 99;
    cpuMoeLayers = 0;
    cacheTypeK = "q8_0";
    cacheTypeV = "q8_0";
    batchSize = 2048;
    microBatchSize = 512;
    parallel = 1;
    enableThinking = false;
    temperature = 0.6;
    topP = 0.95;
    topK = 20;
    minP = 0.0;
    presencePenalty = 0.0;
    repetitionPenalty = 1.0;
  };
  model = repository: revision: file: sha256: settings: {
    preserveThinkingSupported = false;
    artifact = {
      inherit
        repository
        revision
        file
        sha256
        ;
      id = file;
      path = "/var/lib/llama/models/${file}";
    };
    runtime = runtime // settings;
  };
in
rec {
  source = {
    repository = "https://github.com/ggml-org/llama.cpp.git";
    revision = "434ddbbc0e30522e897670681e503b797c12b7c1";
    grammarRepetitionThreshold = 20000;
    installPrefix = "/opt/llama-cpp-opencode";
  };
  defaultModel = "qwen3.6-35b-a3b-mxfp4-moe";
  models."qwen3.6-35b-a3b-mxfp4-moe" = {
    preserveThinkingSupported = true;
    profilePresets = qwenProfiles;
    artifact = {
      id = "Qwen3.6-35B-A3B-GGUF:MXFP4_MOE";
      repository = "unsloth/Qwen3.6-35B-A3B-GGUF";
      revision = "a483e9e6cbd595906af30beda3187c2663a1118c";
      file = "Qwen3.6-35B-A3B-MXFP4_MOE.gguf";
      path = "/var/lib/llama/models/Qwen3.6-35B-A3B-MXFP4_MOE.gguf";
      sha256 = "2fdd20997c4d88ee25f70f500c61f8b999378d92ab055f9d450fc70d617158d3";
    };
    runtime = runtime // {
      cpuMoeLayers = 26;
      microBatchSize = 128;
      threads = 8;
      threadsBatch = 8;
      enableThinking = true;
      temperature = 1.0;
      presencePenalty = 1.5;
    };
  };
  models."qwen3.5-4b-q4-k-m" =
    model "unsloth/Qwen3.5-4B-GGUF" "e87f176479d0855a907a41277aca2f8ee7a09523" "Qwen3.5-4B-Q4_K_M.gguf"
      "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"
      {
        contextSize = 16384;
        chatTemplateFile = ./templates/qwen3.5.jinja;
      };
  models."qwen3.5-9b-q4-k-m" =
    model "unsloth/Qwen3.5-9B-GGUF" "3885219b6810b007914f3a7950a8d1b469d598a5" "Qwen3.5-9B-Q4_K_M.gguf"
      "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"
      { chatTemplateFile = ./templates/qwen3.5.jinja; };
  models."qwen2.5-coder-1.5b-q8-0" =
    model "ggml-org/Qwen2.5-Coder-1.5B-Q8_0-GGUF" "8be1b8a895a84beea772817caaa71eba6b6e0d07"
      "qwen2.5-coder-1.5b-q8_0.gguf"
      "29871c94d15727a6e243f79a37113d4ae625a6215b5e800bf41a23af2da32832"
      {
        contextSize = 4096;
        enableThinking = null;
        temperature = 0.0;
      };
  models."qwen2.5-coder-3b-q4-k-m" =
    model "bartowski/Qwen2.5-Coder-3B-GGUF" "465c183318f1fcb5774394eee76f1b7f224494ec"
      "Qwen2.5-Coder-3B-Q4_K_M.gguf"
      "bf2cee2051affae926e9a9ef4a62ebd197aec86639b075634faf973fcfd8a10c"
      {
        contextSize = 4096;
        enableThinking = null;
        temperature = 0.0;
      };
  server = {
    host = "127.0.0.1";
    port = 11434;
  };
  proxy.localPort = 11435;
}
