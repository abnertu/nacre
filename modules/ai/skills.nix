{ lib, skillSources }:
let
  # Skill name -> path inside its source, grouped by skillSources key.
  bySource.matt-pocock = {
    ask-matt = "skills/engineering/ask-matt";
    "claude-handoff" = "skills/in-progress/claude-handoff";
    "code-review" = "skills/engineering/code-review";
    "codebase-design" = "skills/engineering/codebase-design";
    "diagnosing-bugs" = "skills/engineering/diagnosing-bugs";
    "domain-modeling" = "skills/engineering/domain-modeling";
    "git-guardrails-claude-code" = "skills/misc/git-guardrails-claude-code";
    "grill-me" = "skills/productivity/grill-me";
    "grill-with-docs" = "skills/engineering/grill-with-docs";
    grilling = "skills/productivity/grilling";
    handoff = "skills/productivity/handoff";
    implement = "skills/engineering/implement";
    "improve-codebase-architecture" = "skills/engineering/improve-codebase-architecture";
    "loop-me" = "skills/in-progress/loop-me";
    "migrate-to-shoehorn" = "skills/misc/migrate-to-shoehorn";
    prototype = "skills/engineering/prototype";
    research = "skills/engineering/research";
    "scaffold-exercises" = "skills/misc/scaffold-exercises";
    "setup-pre-commit" = "skills/misc/setup-pre-commit";
    "setup-matt-pocock-skills" = "skills/engineering/setup-matt-pocock-skills";
    "setup-ts-deep-modules" = "skills/in-progress/setup-ts-deep-modules";
    tdd = "skills/engineering/tdd";
    teach = "skills/productivity/teach";
    triage = "skills/engineering/triage";
    "to-questionnaire" = "skills/productivity/to-questionnaire";
    "to-spec" = "skills/engineering/to-spec";
    "to-tickets" = "skills/engineering/to-tickets";
    wayfinder = "skills/engineering/wayfinder";
    wizard = "skills/engineering/wizard";
    "writing-beats" = "skills/in-progress/writing-beats";
    "writing-fragments" = "skills/in-progress/writing-fragments";
    "writing-shape" = "skills/in-progress/writing-shape";
    "writing-for-agents" = "skills/productivity/writing-for-agents";
  };
  bySource.vercel = {
    "find-skills" = "skills/find-skills";
  };
  bySource.obsidian = lib.genAttrs [
    "defuddle"
    "json-canvas"
    "knap"
    "obsidian-bases"
    "obsidian-cli"
    "obsidian-markdown"
  ] (name: "skills/${name}");
  bySource.gh = lib.genAttrs [
    "gh"
    "gh-skill"
  ] (name: "skills/${name}");
  bySource.abnertu = lib.genAttrs [
    "converge"
    "setup-agent-prefs"
    "setup-repo-docs"
  ] (name: "skills/${name}");
  # Optional sets register their skills only when the caller supplies their source.
  optionalSources = [
    "gh"
    "abnertu"
  ];
  enabledBySource = lib.filterAttrs (
    source: _: !(builtins.elem source optionalSources) || skillSources ? ${source}
  ) bySource;
  owner = lib.concatMapAttrs (source: lib.mapAttrs (_: _: source)) enabledBySource;
  registry = lib.concatMapAttrs (_: paths: paths) enabledBySource;
  sourceOf = name: skillSources.${owner.${name}};
  roots = lib.mapAttrs (name: path: sourceOf name + "/${path}") registry;
  allNames = builtins.attrNames roots;
  resolveSource =
    name: source:
    let
      path = registry.${name} or (throw "unknown AI skill selection '${name}'");
      skill = source + "/${path}";
    in
    lib.assertMsg (builtins.pathExists (
      skill + "/SKILL.md"
    )) "AI skill '${name}' is selected but source ${toString skill}/SKILL.md is missing";
  resolve =
    name:
    if !(builtins.hasAttr name roots) then
      throw "unknown AI skill selection '${name}'"
    else
      resolveSource name (sourceOf name);
in
{
  inherit registry roots;
  inherit resolve resolveSource;
  selected = builtins.listToAttrs (
    map (name: {
      inherit name;
      value =
        assert resolve name;
        roots.${name};
    }) allNames
  );
}
