# The AI feature: selected llama models and profiles, the artifacts that
# preparation fetches, and the home files of Codex, Claude and agent skills.
{
  lib,
  config,
  # Locked skill inputs and the packaged GitHub CLI source, passed by composition.
  skillSources ? { },
}:
let
  llama = config.enable && config.llama.enable;
  inventory = import ./artifacts.nix;
  clean = value: lib.filterAttrs (_: item: item != null) value;
  resolvedModels = import ./resolved-models.nix {
    inherit lib;
    inherit (config) llama;
  };
  defaultModelName = config.llama.model.name;
  modelArtifacts = resolvedModels.models;
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
      artifacts = selected // overrides;
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
    concurrentModels = config.llama.concurrentModels;
  };
  homeModule = {
    home.file = lib.optionalAttrs config.enable (
      let
        agentSkillsEnabled = config.skills.enable && config.skills.agents.enable;
        claudeSkillsEnabled = config.skills.enable && config.claude.enable && config.skills.claude.enable;
        skills =
          if agentSkillsEnabled || claudeSkillsEnabled then
            import ./skills.nix {
              inherit lib;
              inherit (config.skills) exclude;
              sets = config.skills.sets;
              builtinSets = lib.filterAttrs (name: _: config.skills.builtins.${name}.enable) (
                import ./skill-inventory.nix {
                  inherit lib;
                  sources = skillSources;
                }
              );
            }
          else
            null;
        agentSkills =
          if agentSkillsEnabled then
            lib.mapAttrs' (
              name: source: lib.nameValuePair ".agents/skills/${name}" { inherit source; }
            ) skills.selected
          else
            { };
        claudeSkills =
          if claudeSkillsEnabled then
            lib.mapAttrs' (
              name: source: lib.nameValuePair ".claude/skills/${name}" { inherit source; }
            ) skills.selected
          else
            { };
      in
      agentSkills
      // claudeSkills
      // lib.optionalAttrs codexLocalProfileEnabled {
        ".codex/llama-cpp.config.toml" = {
          text = codexLocalProfile;
        };
      }
    );
  };
}
