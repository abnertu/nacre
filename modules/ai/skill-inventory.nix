# The built-in skill inventory: explicit selected paths and their locked sources.
{ lib, sources }:
let
  # Skill name -> path inside its source, grouped by built-in bundle.
  bySource.mattpocock = {
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
  sourceKeys = {
    mattpocock = "matt-pocock-skills";
    obsidian = "obsidian-skills";
    vercel = "vercel-skills";
    abnertu = "abnertu-skills";
    gh = "gh";
  };
in
lib.mapAttrs (name: skills: {
  source =
    sources.${sourceKeys.${name}} or (throw "missing source for built-in AI skill bundle '${name}'");
  inherit skills;
}) bySource
