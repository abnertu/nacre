# Legacy skill switches forward to the canonical skill options in either evaluator.
{
  prefix ? [ ],
}:
{ lib, ... }:
{
  imports = [
    (lib.mkAliasOptionModule
      (
        prefix
        ++ [
          "skillsPresets"
          "enable"
        ]
      )
      (
        prefix
        ++ [
          "skills"
          "agents"
          "enable"
        ]
      )
    )
    (lib.mkAliasOptionModule
      (
        prefix
        ++ [
          "claude"
          "skills"
          "enable"
        ]
      )
      (
        prefix
        ++ [
          "skills"
          "claude"
          "enable"
        ]
      )
    )
    (lib.mkAliasOptionModule
      (
        prefix
        ++ [
          "skills"
          "gh"
          "enable"
        ]
      )
      (
        prefix
        ++ [
          "skills"
          "builtins"
          "gh"
          "enable"
        ]
      )
    )
  ];
}
