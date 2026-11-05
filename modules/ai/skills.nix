# Agent skills selected from skill sets. A set is a source tree and the skills
# it provides, each a directory with a SKILL.md, given by its path inside the
# source. Machine flakes declare their sets through programs.ai.skills.sets.
{ lib, sets }:
let
  # Skill name -> { set, path } across all sets; a name may come from one set.
  registry = lib.foldlAttrs (
    acc: setName: set:
    acc
    // lib.mapAttrs (
      name: path:
      if acc ? ${name} then
        throw "AI skill '${name}' is provided by both '${acc.${name}.set}' and '${setName}'"
      else
        {
          set = setName;
          inherit path;
        }
    ) set.skills
  ) { } sets;

  root = name: "${sets.${registry.${name}.set}.source}/${registry.${name}.path}";

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
  selected = lib.mapAttrs (name: _: resolve name) registry;
}
