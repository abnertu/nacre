{
  lib,
  config,
  skillSources ? { },
}:
let
  llama = config.enable && config.llama.enable;
  inventory = import ./artifacts.nix;
  clean = value: lib.filterAttrs (_: item: item != null) value;
  legacyModel = config.llama.model;
  legacyName = legacyModel.name;
  legacyOverrides = clean (builtins.removeAttrs legacyModel [ "name" ]);
  configuredModels = config.llama.models;
  explicitlyConfigured = configuredModels != { };
  selectedNames =
    let
      enabled = lib.filterAttrs (_: model: model.enable) configuredModels;
    in
    if explicitlyConfigured then builtins.attrNames enabled else [ legacyName ];
  defaultModelName = legacyName;
  modelArtifacts = lib.genAttrs selectedNames (
    name:
    let
      declared = inventory.models.${name};
      configured = configuredModels.${name} or { };
      legacy = if name == legacyName then legacyOverrides else { };
      overrides = clean (builtins.removeAttrs configured [ "enable" ]);
      fallbackDevice = if legacyModel.device == null then { } else { device = legacyModel.device; };
      effective = declared.artifact // declared.runtime // fallbackDevice // legacy // overrides;
    in
    effective
    // lib.optionalAttrs (effective.preserveThinking or null == true) {
      enableThinking = null;
    }
  );
  profileInputs = config.llama.profiles // {
    default = {
      model = defaultModelName;
    }
    // (config.llama.profiles.default or { });
  };
  profiles = lib.mapAttrs (
    _: profile:
    let
      selectedName = if profile.model == null then defaultModelName else profile.model;
      selected = modelArtifacts.${selectedName};
      overrides = clean (builtins.removeAttrs profile [ "model" ]);
    in
    {
      model = selectedName;
      artifacts =
        selected
        // overrides
        // lib.optionalAttrs (profile.preserveThinking or null == true) {
          enableThinking = null;
        };
    }
  ) profileInputs;
  codexLocalProfileEnabled =
    config.enable && config.codex.enable && llama && config.codex.localProfile.enable;
  codexLocalProfile =
    let
      selectedName = profiles.default.model;
      model = inventory.models.${selectedName};
      contextSize = profiles.default.artifacts.contextSize;
      compactAt = builtins.div (contextSize * 3) 4;
      tomlString = value: builtins.toJSON value;
    in
    ''
      model = ${tomlString model.artifact.id}
      model_context_window = ${toString contextSize}
      model_auto_compact_token_limit = ${toString compactAt}
      model_provider = "llama_cpp"
      web_search = "disabled"

      [features]
      multi_agent = false

      [model_providers.llama_cpp]
      name = "llama.cpp (llama-swap)"
      base_url = "http://127.0.0.1:${toString inventory.server.port}/v1"
      wire_api = "responses"
      requires_openai_auth = false
      supports_websockets = false
    '';
in
{
  inherit llama;
  artifacts = inventory // {
    model = profiles.default.artifacts;
    models = modelArtifacts;
    inherit profiles;
    server = inventory.server // {
      modelsMax = config.llama.maxLoadedModels;
    };
    concurrentModels = config.llama.concurrentModels;
  };
  homeModule = {
    home.file = lib.optionalAttrs config.enable (
      let
        skills =
          if config.skillsPresets.enable || (config.agy.enable && config.agy.skills.enable) then
            import ./skills.nix {
              inherit lib skillSources;
            }
          else
            null;
        agentSkills =
          if config.skillsPresets.enable then
            assert skills.validateCustom skills.agentCustomRoots;
            lib.mapAttrs' (name: source: lib.nameValuePair ".agents/skills/${name}" { inherit source; }) (
              skills.agentCustomRoots // skills.selected
            )
          else
            { };
        geminiSkills =
          if skills != null && config.agy.enable && config.agy.skills.enable then
            assert skills.validateCustom skills.geminiCustomRoots;
            lib.mapAttrs' (
              name: source: lib.nameValuePair ".gemini/config/skills/${name}" { inherit source; }
            ) (skills.geminiCustomRoots // skills.selected)
          else
            { };
      in
      agentSkills
      // geminiSkills
      // lib.optionalAttrs codexLocalProfileEnabled {
        ".codex/llama-cpp.config.toml" = {
          text = codexLocalProfile;
        };
      }
    );
  };
}
