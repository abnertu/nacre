# Skill selection through fixture machine composition, including legacy options.
{ lib, inputs }:
let
  fixtures = import ./lib.nix { inherit lib inputs; };
  files = raw: (fixtures.home [ { programs.ai = raw; } ] "fixture").config.home.file;
  targets = [
    ".agents/skills/"
    ".claude/skills/"
  ];
  hasBoth = home: name: lib.all (target: builtins.hasAttr "${target}${name}" home) targets;
  hasNeither = home: name: lib.all (target: !(builtins.hasAttr "${target}${name}" home)) targets;
  skillFiles =
    home: lib.filterAttrs (name: _: lib.any (target: lib.hasPrefix target name) targets) home;
  valid = raw: (builtins.tryEval (builtins.deepSeq (skillFiles (files raw)) true)).success;

  bundleOff = files {
    skills.builtins.abnertu.enable = false;
    skills.exclude = [ "converge" ];
  };
  excluded = files {
    skills.exclude = [
      "converge"
      "unmatched-exclusion"
    ];
  };
  customOff = files { skills.sets.personal.enable = false; };
  allOff = files { skills.enable = false; };
  agentsOff = files { skills.agents.enable = false; };
  claudeOff = files { skills.claude.enable = false; };
  claudeToolOff = files { claude.enable = false; };

  replacement = {
    source = ./fixtures/skills/personal;
    skills.replacement = "skills/sample-personal";
  };
  replaced = files {
    skills.builtins.abnertu.enable = false;
    skills.sets.abnertu = replacement;
  };
  missing = {
    source = ./fixtures/skills/personal;
    skills.absent = "skills/absent";
  };

  # Source arguments must remain lazy when their bundle or both targets are off.
  unavailableSources = inputs // {
    matt-pocock-skills = throw "unused Matt Pocock source evaluated";
  };
  sourceFixtures = import ./lib.nix {
    inherit lib;
    inputs = unavailableSources;
  };
  sourceFiles = raw: (sourceFixtures.home [ { programs.ai = raw; } ] "fixture").config.home.file;
  forcedSourceFiles = raw: builtins.deepSeq (skillFiles (sourceFiles raw)) true;

  aliases = [
    {
      old = [
        "skillsPresets"
        "enable"
      ];
      canonical = [
        "skills"
        "agents"
        "enable"
      ];
    }
    {
      old = [
        "claude"
        "skills"
        "enable"
      ];
      canonical = [
        "skills"
        "claude"
        "enable"
      ];
    }
    {
      old = [
        "skills"
        "gh"
        "enable"
      ];
      canonical = [
        "skills"
        "builtins"
        "gh"
        "enable"
      ];
    }
  ];
  # Exercise both evaluator entry points; forwarded definitions must still conflict.
  aliasWorks =
    alias:
    let
      raw = lib.setAttrByPath alias.old false;
      conflict = lib.recursiveUpdate raw (lib.setAttrByPath alias.canonical true);
      machine = value: (fixtures.evaluate [ { programs.ai = value; } ]).config.programs.ai;
      standalone =
        value:
        import ../modules/ai/interface.nix {
          inherit lib;
          raw = value;
        };
      works =
        evaluate:
        let
          evaluated = evaluate raw;
        in
        !(lib.getAttrFromPath alias.canonical evaluated)
        && !(lib.getAttrFromPath alias.old evaluated)
        && !(builtins.tryEval (builtins.deepSeq (evaluate conflict) true)).success;
    in
    works machine && works standalone;
in
assert hasNeither bundleOff "converge" && hasBoth bundleOff "gh";
assert hasNeither excluded "converge" && hasBoth excluded "setup-agent-prefs";
assert hasNeither customOff "sample-personal" && hasBoth customOff "sample-upstream";
assert skillFiles allOff == { } && allOff ? ".codex/llama-cpp.config.toml";
assert lib.filterAttrs (name: _: lib.hasPrefix ".agents/skills/" name) agentsOff == { };
assert agentsOff ? ".claude/skills/sample-personal";
assert lib.filterAttrs (name: _: lib.hasPrefix ".claude/skills/" name) claudeOff == { };
assert claudeOff ? ".agents/skills/sample-personal";
assert lib.filterAttrs (name: _: lib.hasPrefix ".claude/skills/" name) claudeToolOff == { };
assert claudeToolOff ? ".agents/skills/sample-personal";
assert !(valid { skills.sets.abnertu = replacement; });
assert hasBoth replaced "replacement" && hasNeither replaced "converge";
assert
  !(valid {
    skills.sets.copy = {
      source = ./fixtures/skills/personal;
      skills.converge = "skills/sample-personal";
    };
    skills.exclude = [ "converge" ];
  });
assert !(valid { skills.sets.missing = missing; });
assert valid {
  skills.sets.missing = missing // {
    enable = false;
  };
};
assert valid {
  skills.sets.missing = missing;
  skills.exclude = [ "absent" ];
};
assert !(builtins.tryEval (forcedSourceFiles { })).success;
assert forcedSourceFiles { skills.builtins.mattpocock.enable = false; };
assert forcedSourceFiles { skills.enable = false; };
assert forcedSourceFiles {
  skills.agents.enable = false;
  skills.claude.enable = false;
};
assert lib.all aliasWorks aliases;
true
