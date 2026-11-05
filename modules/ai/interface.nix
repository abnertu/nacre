# Evaluate raw AI settings into the typed AI configuration, filling profile
# presets from the model inventory.
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
  resolvedModels = import ./resolved-models.nix {
    inherit lib;
    inherit (result) llama;
  };
  selectedModelNames = resolvedModels.selectedNames;
  effectiveModels = builtins.attrValues resolvedModels.models;
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
      known = lib.all (name: builtins.hasAttr name inventory) resolvedModels.configuredNames;
      selectedCount = builtins.length selectedModelNames;
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
      model = resolvedModels.models.${name};
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
