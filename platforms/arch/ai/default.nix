{
  lib,
  pkgs,
  config,
  artifacts,
  tailscale,
}:
let
  llama = config.enable && config.llama.enable;
  proxy = llama && config.llama.proxy.enable && tailscale;
  modelProfiles =
    modelName:
    let
      matching = lib.filterAttrs (_: profile: profile.model == modelName) artifacts.profiles;
    in
    matching
    // lib.optionalAttrs (!(builtins.hasAttr "default" matching)) {
      default = {
        model = modelName;
        artifacts = artifacts.models.${modelName};
      };
    };
  profileAlias =
    name: profile:
    if name == "default" then profile.artifacts.id else "${profile.artifacts.id}:${name}";
  chatTemplateKwargs =
    profile:
    lib.filterAttrs (_: value: value != null) {
      reasoning_effort = profile.artifacts.reasoningEffort or null;
      enable_thinking = profile.artifacts.enableThinking or null;
      preserve_thinking = profile.artifacts.preserveThinking or null;
    };
  requestParams =
    profile:
    {
      temperature = profile.artifacts.temperature;
      top_p = profile.artifacts.topP;
      top_k = profile.artifacts.topK;
      min_p = profile.artifacts.minP;
      presence_penalty = profile.artifacts.presencePenalty;
      repetition_penalty = profile.artifacts.repetitionPenalty;
    }
    // lib.optionalAttrs (chatTemplateKwargs profile != { }) {
      chat_template_kwargs = chatTemplateKwargs profile;
    };
  switcherModels = lib.mapAttrs' (
    modelName: model:
    let
      profiles = modelProfiles modelName;
      runtimeModel = model // profiles.default.artifacts;
      aliases = lib.filter (alias: alias != model.id) (lib.mapAttrsToList profileAlias profiles);
      paramsById = lib.mapAttrs' (
        name: profile: lib.nameValuePair (profileAlias name profile) (requestParams profile)
      ) profiles;
      command = lib.concatStringsSep " " (
        [
          "${artifacts.source.installPrefix}/current/bin/llama-server"
          "--model ${lib.escapeShellArg runtimeModel.path}"
          "--host 127.0.0.1"
          "--port \${PORT}"
          "--no-webui"
          "--ctx-size ${toString runtimeModel.contextSize}"
          "--fit ${if runtimeModel.fit or true then "on" else "off"}"
          "--fit-target ${toString runtimeModel.fitTarget}"
          "--flash-attn on"
          "--cache-type-k ${runtimeModel.cacheTypeK}"
          "--cache-type-v ${runtimeModel.cacheTypeV}"
          "--batch-size ${toString runtimeModel.batchSize}"
          "--ubatch-size ${toString runtimeModel.microBatchSize}"
          "--parallel ${toString runtimeModel.parallel}"
          "--device ${runtimeModel.device}"
        ]
        ++ lib.optional (
          runtimeModel.chatTemplateFile or null != null
        ) "--chat-template-file ${lib.escapeShellArg "${runtimeModel.chatTemplateFile}"}"
        ++ lib.optional (
          runtimeModel.gpuLayers or null != null
        ) "--n-gpu-layers ${toString runtimeModel.gpuLayers}"
        ++ lib.optional (
          runtimeModel.cpuMoeLayers or null != null
        ) "--n-cpu-moe ${toString runtimeModel.cpuMoeLayers}"
      );
    in
    lib.nameValuePair model.id {
      cmd = command;
      proxy = "http://127.0.0.1:\${PORT}";
      checkEndpoint = "/health";
      inherit aliases;
      filters.setParamsByID = paramsById;
    }
  ) artifacts.models;
  switcher = {
    startPort = artifacts.server.port + 1000;
    includeAliasesInList = true;
    globalTTL = 0;
    groups.default = {
      swap = !(artifacts.concurrentModels or false);
      exclusive = !(artifacts.concurrentModels or false);
      persistent = artifacts.concurrentModels or false;
      members = map (model: model.id) (builtins.attrValues artifacts.models);
    };
    models = switcherModels;
  };
  legacyModel = artifacts.legacy.model;
  legacyServer = artifacts.legacy.server;
  prefix = artifacts.source.installPrefix + "/current";
  legacyChatTemplateKwargs =
    "{"
    + lib.concatStringsSep "," (
      lib.filter (value: value != null) [
        (
          if legacyModel.reasoningEffort or null == null then
            null
          else
            ''"reasoning_effort":${builtins.toJSON legacyModel.reasoningEffort}''
        )
        (
          if legacyModel.enableThinking or null == null then
            null
          else
            ''"enable_thinking":${builtins.toJSON legacyModel.enableThinking}''
        )
        (
          if legacyModel.preserveThinking or null == null then
            null
          else
            ''"preserve_thinking":${builtins.toJSON legacyModel.preserveThinking}''
        )
      ]
    )
    + "}";
  escapedChatTemplateKwargs = lib.replaceStrings [ "\"" ] [ "\\\"" ] (legacyChatTemplateKwargs);
  reasoningEffort = lib.optionalString (
    legacyModel.reasoningEffort or null != null
  ) " --reasoning-effort ${legacyModel.reasoningEffort}";
  switcherConfig = builtins.toJSON {
    inherit (switcher)
      startPort
      includeAliasesInList
      globalTTL
      groups
      models
      ;
  };
  switcherUnit = ''
    [Unit]
    Description=Nix-config llama-swap model router
    After=network-online.target
    Wants=network-online.target

    [Service]
    Environment=LD_LIBRARY_PATH=${prefix}/lib:${prefix}/lib64
    ExecStart=${lib.optionalString llama "${pkgs.llama-swap}/bin/llama-swap"} --config /etc/llama-swap/config.yaml --listen 127.0.0.1:${toString artifacts.server.port}
    Restart=on-failure
    RestartSec=3

    [Install]
    WantedBy=multi-user.target
  '';
  caddyMain = ''
    {
        admin "unix//run/caddy/admin.socket"
    }

    import /etc/caddy/conf.d/*
  '';
  packageCaddy = builtins.readFile ./package-caddy.Caddyfile;
  packageCaddyWithSite =
    lib.replaceStrings
      [ "# Import additional caddy config files in /etc/caddy/conf.d/\n" ]
      [ "${legacyCaddySite}\n# Import additional caddy config files in /etc/caddy/conf.d/\n" ]
      packageCaddy;
  caddySite = ''
    :${toString artifacts.proxy.localPort} {
        bind 127.0.0.1

        @api path /health /v1/*
        handle @api {
            reverse_proxy 127.0.0.1:${toString artifacts.server.port} {
                header_up Host 127.0.0.1:${toString artifacts.server.port}
            }
        }

        respond 404
    }
  '';
  legacyCaddySite = lib.replaceStrings [ "    " ] [ "\t" ] caddySite;
  legacyPreset = ''
    version = 1

    [*]
    parallel = ${toString legacyModel.parallel}
    cont-batching = true
    jinja = true

    [${legacyModel.id}]
    model = ${legacyModel.path}
    device = ${legacyModel.device}
    ctx-size = ${toString legacyModel.contextSize}
    fit = true
    fit-target = ${toString legacyModel.fitTarget}
    fit-ctx = ${toString legacyModel.contextSize}
    flash-attn = on
    cache-type-k = ${legacyModel.cacheTypeK}
    cache-type-v = ${legacyModel.cacheTypeV}
    batch-size = ${toString legacyModel.batchSize}
    ubatch-size = ${toString legacyModel.microBatchSize}
    load-on-startup = true
  '';
  legacyDropin = ''
    [Unit]
    After=network-online.target

    [Service]
    Environment=LD_LIBRARY_PATH=${prefix}/lib:${prefix}/lib64
    ExecStart=
    ExecStart=${prefix}/bin/llama-server --models-preset /etc/llama/server/models.ini --models-max ${toString legacyServer.modelsMax} --host ${legacyServer.host} --port ${toString legacyServer.port} --no-webui --temp ${builtins.toJSON legacyModel.temperature} --top-p ${builtins.toJSON legacyModel.topP} --top-k ${toString legacyModel.topK} --min-p ${builtins.toJSON legacyModel.minP} --presence-penalty ${builtins.toJSON legacyModel.presencePenalty} --repeat-penalty ${builtins.toJSON legacyModel.repetitionPenalty}${reasoningEffort} --chat-template-kwargs ${escapedChatTemplateKwargs}
    SupplementaryGroups=render video
    Restart=on-failure
    RestartSec=3
  '';
in
{
  inherit llama proxy;
  manifest = pkgs.writeText "arch-ai.json" (
    builtins.toJSON {
      inherit llama proxy;
      inherit (artifacts)
        source
        server
        profiles
        legacy
        ;
      switcher = {
        binary = lib.optionalString llama "${pkgs.llama-swap}/bin/llama-swap";
        listen = "127.0.0.1:${toString artifacts.server.port}";
      }
      // switcher;
      models = artifacts.models;
      model = artifacts.model;
      localPort = artifacts.proxy.localPort;
      inherit (config.llama.proxy) httpsPort;
      paths = {
        switcherConfig = "/etc/llama-swap/config.yaml";
        switcherUnit = "/etc/systemd/system/llama-swap.service";
        legacyPreset = "/etc/llama/server/models.ini";
        legacyDropin = "/etc/systemd/system/llama-server.service.d/60-nix-config.conf";
        legacyLocalDropin = "/etc/systemd/system/llama-server.service.d/60-local.conf";
        caddyMain = "/etc/caddy/Caddyfile";
        caddySite = "/etc/caddy/conf.d/nix-config-llama.caddy";
        legacyOllamaSite = "/etc/caddy/conf.d/nix-config-ollama.caddy";
      };
      generated = {
        inherit
          switcherConfig
          switcherUnit
          caddyMain
          caddySite
          packageCaddy
          packageCaddyWithSite
          legacyPreset
          legacyDropin
          ;
      };
    }
  );
}
