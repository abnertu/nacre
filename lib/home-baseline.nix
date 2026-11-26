# Home defaults that a machine's plain definition or lib.mkDefault replaces.
# Each leaf gets priority 1100, as roles use. Lists keep normal priority, so a
# machine's list adds to them. Derivations, flake inputs, paths and module-system values
# (mkIf, mkMerge, overrides) stay whole: apply this inside a mkIf body.
lib:
let
  baseline =
    value:
    if builtins.isList value then
      value
    # Derivations and flake inputs carry outPath: they are leaves too.
    else if builtins.isAttrs value && !(value ? outPath) && !(value ? _type) then
      lib.mapAttrs (_: baseline) value
    else
      lib.mkOverride 1100 value;
in
baseline
