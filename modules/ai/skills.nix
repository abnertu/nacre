{ lib, skillSources }:
let
  matt = skillSources.matt-pocock;
  vercel = skillSources.vercel;
  upstream = {
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
  custom = [
    "obsidian-vault"
  ];
  sourceFor = name: path: if name == "find-skills" then vercel + "/${path}" else matt + "/${path}";
  registry = upstream // {
    "find-skills" = "skills/find-skills";
  };
  roots = lib.mapAttrs (name: path: sourceFor name path) registry;
  agentCustomRoots = lib.genAttrs custom (name: ../../files/home/.agents/skills + "/${name}");
  geminiCustomRoots = lib.genAttrs custom (name: ../../files/home/.gemini/config/skills + "/${name}");
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
      resolveSource name (if name == "find-skills" then vercel else matt);
in
assert lib.assertMsg (lib.all (
  name: !(builtins.elem name allNames)
) custom) "AI skill registry overlaps retained custom skills";
{
  inherit custom registry roots;
  inherit resolve resolveSource;
  inherit agentCustomRoots geminiCustomRoots;
  validateCustom =
    roots':
    lib.all (
      name:
      let
        source = roots'.${name};
      in
      lib.assertMsg (builtins.pathExists (
        source + "/SKILL.md"
      )) "retained custom AI skill '${name}' is missing SKILL.md at ${toString source}/SKILL.md"
    ) custom;
  selected = builtins.listToAttrs (
    map (name: {
      inherit name;
      value =
        assert resolve name;
        roots.${name};
    }) allNames
  );
}
