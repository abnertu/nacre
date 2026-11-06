# Merge enabled skill sets, reject conflicting ownership, and resolve selected paths.
{
  lib,
  sets,
  builtinSets ? { },
  exclude ? [ ],
}:
let
  customSets = lib.filterAttrs (_: set: set.enable or true) sets;
  collisions = lib.intersectLists (builtins.attrNames builtinSets) (builtins.attrNames customSets);
  enabledSets =
    lib.throwIf (collisions != [ ])
      "AI skill sets conflict with built-in bundles: ${lib.concatStringsSep ", " collisions}; disable programs.ai.skills.builtins.<bundle>.enable to supply replacements"
      (builtinSets // customSets);
  # Skill name -> { set, path } across all sets; a name may come from one set.
  registry = lib.foldlAttrs (
    acc: setName: set:
    let
      duplicates = lib.intersectLists (builtins.attrNames acc) (builtins.attrNames set.skills);
      name = builtins.head duplicates;
    in
    lib.throwIf (duplicates != [ ])
      "AI skill '${name}' is provided by both '${acc.${name}.set}' and '${setName}'"
      (
        acc
        // lib.mapAttrs (_: path: {
          set = setName;
          inherit path;
        }) set.skills
      )
  ) { } enabledSets;

  root = name: "${enabledSets.${registry.${name}.set}.source}/${registry.${name}.path}";

  # The skill directory of `name`, once its SKILL.md is known to exist.
  resolve =
    name:
    let
      skill = if registry ? ${name} then root name else throw "unknown AI skill selection '${name}'";
    in
    lib.throwIfNot (builtins.pathExists "${skill}/SKILL.md")
      "AI skill '${name}' is selected but ${skill}/SKILL.md is missing"
      skill;
in
{
  inherit registry resolve;
  selected = lib.mapAttrs (name: _: resolve name) (builtins.removeAttrs registry exclude);
}
