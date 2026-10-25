{
  lib,
  raw ? { },
}:
let
  result =
    (lib.evalModules {
      modules = [
        { options = import ./options.nix { inherit lib; }; }
        (
          { config, ... }:
          let
            defaults = inventory.${config.llama.model.name}.profilePresets or { };
            names = lib.unique (builtins.attrNames defaults ++ builtins.attrNames (raw.llama.profiles or { }));
            fields = lib.unique (
              lib.concatMap builtins.attrNames (
                lib.concatMap (model: builtins.attrValues (model.profilePresets or { })) (
                  builtins.attrValues inventory
                )
              )
            );
          in
          {
            llama.profiles = lib.genAttrs names (
              name:
              lib.genAttrs fields (
                field:
                lib.mkDefault (
                  let
                    target = config.llama.profiles.${name}.model;
                    selected = if target == null then config.llama.model.name else target;
                  in
                  inventory.${selected}.profilePresets.${name}.${field} or null
                )
              )
            );
          }
        )
        raw
      ];
    }).config;
  inventory = (import ./artifacts.nix).models;
  configuredModelNames = builtins.attrNames result.llama.models;
  selectedModelNames =
    let
      enabled = lib.filter (name: result.llama.models.${name}.enable) configuredModelNames;
    in
    if configuredModelNames == [ ] then [ result.llama.model.name ] else enabled;
  effectiveModels = map (
    name:
    let
      configured = result.llama.models.${name} or { };
      clean = value: lib.filterAttrs (_: item: item != null) value;
      legacyOverrides = clean (builtins.removeAttrs result.llama.model [ "name" ]);
      modelOverrides = clean (builtins.removeAttrs configured [ "enable" ]);
      effective =
        inventory.${name}.runtime
        // (if name == result.llama.model.name then legacyOverrides else { })
        // modelOverrides;
    in
    effective
  ) selectedModelNames;
  effectiveDefaultModel = result.llama.model.name;
in
assert lib.assertMsg (
  result.llama.model.microBatchSize == null
  || result.llama.model.batchSize == null
  || result.llama.model.microBatchSize <= result.llama.model.batchSize
) "llama.cpp micro-batch size must not exceed batch size";
assert lib.assertMsg
  (
    let
      names = builtins.attrNames result.llama.models;
      selected = lib.filter (name: result.llama.models.${name}.enable) names;
      known = lib.all (name: builtins.hasAttr name (import ./artifacts.nix).models) names;
      selectedCount = if names == [ ] then 1 else builtins.length selected;
    in
    known
    && selectedCount > 0
    && builtins.elem result.llama.model.name selectedModelNames
    && (
      if result.llama.concurrentModels then
        selectedCount <= result.llama.maxLoadedModels
      else
        result.llama.maxLoadedModels == 1
    )
    && lib.all (
      profile:
      builtins.elem (
        if profile.model == null then effectiveDefaultModel else profile.model
      ) selectedModelNames
    ) (builtins.attrValues result.llama.profiles)
  )
  "llama.cpp selections must be known; profiles must target selected models; maxLoadedModels must match the concurrency policy";
assert lib.assertMsg (lib.all (
  model: model.microBatchSize <= model.batchSize
) effectiveModels) "llama.cpp effective model micro-batch size must not exceed batch size";
assert lib.assertMsg (
  result.llama.memoryBudgetMiB == null
  || (
    lib.all (model: model ? vramEstimateMiB) effectiveModels
    && lib.all (model: model.vramEstimateMiB != null) effectiveModels
    &&
      lib.foldl' (
        total: model:
        if result.llama.concurrentModels then
          total + model.vramEstimateMiB
        else
          lib.max total model.vramEstimateMiB
      ) 0 effectiveModels <= result.llama.memoryBudgetMiB
  )
) "llama.cpp selected model VRAM estimates must be declared and fit within memoryBudgetMiB";
assert lib.assertMsg (
  lib.all (
    name:
    let
      model = builtins.elemAt effectiveModels (
        lib.lists.findFirstIndex (candidate: candidate == name) 0 selectedModelNames
      );
    in
    model.preserveThinking or null != true || inventory.${name}.preserveThinkingSupported
  ) selectedModelNames
  && lib.all (
    profile:
    let
      name = if profile.model == null then effectiveDefaultModel else profile.model;
    in
    profile.preserveThinking != true || inventory.${name}.preserveThinkingSupported
  ) (builtins.attrValues result.llama.profiles)
) "llama.cpp reasoning preservation requires a supporting model template";
builtins.deepSeq result result
