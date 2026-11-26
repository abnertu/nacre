# environment.etc: text files under /etc that the core adapter writes, records
# and withdraws. Names are relative to /etc, as in NixOS.
{ lib, ... }:
let
  inherit (lib) mkOption types;
  entry = types.submodule (
    {
      name,
      config,
      options,
      ...
    }:
    {
      options = {
        enable = mkOption {
          type = types.bool;
          default = true;
          description = "Whether Nacre writes this file. A disabled entry is withdrawn like a removed one.";
        };
        text = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "File content. Never put secrets here: the text lands in the Nix store and the manifest.";
        };
        source = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Text file whose content Nacre writes, in place of `text`.";
        };
        mode = mkOption {
          type = types.strMatching "0[0-7]{3}";
          default = "0644";
          description = "Octal file mode.";
        };
        group = mkOption {
          type = types.strMatching "[a-z_][a-z0-9_-]*";
          default = "root";
          description = "Owning group. The file owner is root.";
        };
        adopt = mkOption {
          type = types.bool;
          default = false;
          description = ''
            Replace an existing file that differs and that Nacre does not record.
            Nacre saves the original and restores it when the entry goes away.
          '';
        };
        action = mkOption {
          type = types.nullOr types.str;
          default = null;
          internal = true;
          description = "Core restart action that a change of this file marks.";
        };
        content = mkOption {
          type = types.nullOr types.str;
          internal = true;
          readOnly = true;
          description = "The text that wins between `text` and `source` by priority; null on a conflict.";
        };
        contentError = mkOption {
          type = types.nullOr types.str;
          internal = true;
          readOnly = true;
          description = "Why the entry has no content, for its assertion.";
        };
      };
      config =
        let
          hasText = config.text != null;
          hasSource = config.source != null;
          textPrio = options.text.highestPrio;
          sourcePrio = options.source.highestPrio;
        in
        {
          content =
            if hasText && hasSource then
              if textPrio < sourcePrio then
                config.text
              else if sourcePrio < textPrio then
                builtins.readFile config.source
              else
                null
            else if hasText then
              config.text
            else if hasSource then
              builtins.readFile config.source
            else
              null;
          contentError =
            if hasText && hasSource && textPrio == sourcePrio then
              "environment.etc.\"${name}\" defines both text and source at the same priority"
            else if !hasText && !hasSource then
              "environment.etc.\"${name}\" defines neither text nor source"
            else
              null;
        };
    }
  );
in
{
  options.environment.etc = mkOption {
    type = types.attrsOf entry;
    default = { };
    description = "Text files under /etc. Each name is a path relative to /etc.";
  };
}
