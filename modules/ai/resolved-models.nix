# Resolve enabled model artifacts and runtime overrides once for validation
# and generated configuration. Per-model fields win over default-model fields.
{ lib, llama }:
let
  inventory = (import ./artifacts.nix).models;
  clean = value: lib.filterAttrs (_: item: item != null) value;
  defaultName = llama.model.name;
  defaultOverrides = clean (builtins.removeAttrs llama.model [ "name" ]);
  configuredNames = builtins.attrNames llama.models;
  selectedNames =
    if configuredNames == [ ] then
      [ defaultName ]
    else
      lib.filter (name: llama.models.${name}.enable) configuredNames;
  # Preserve the default device for other selected models unless overridden.
  fallbackDevice = lib.optionalAttrs (llama.model.device != null) {
    inherit (llama.model) device;
  };
  models = lib.genAttrs selectedNames (
    name:
    let
      declared = inventory.${name};
      configured = llama.models.${name} or { };
      defaults = lib.optionalAttrs (name == defaultName) defaultOverrides;
      overrides = clean (builtins.removeAttrs configured [ "enable" ]);
    in
    declared.artifact // declared.runtime // fallbackDevice // defaults // overrides
  );
in
{
  inherit configuredNames selectedNames models;
}
