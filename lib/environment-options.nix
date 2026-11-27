# environment.etc: files and symlinks under /etc that the core adapter writes,
# records and withdraws. Names are relative to /etc, as in NixOS.
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
          type = types.nullOr (types.either types.path types.str);
          default = null;
          description = "Store file whose bytes Nacre copies, in place of `text`. It may be binary.";
        };
        target = mkOption {
          type = types.nullOr types.str;
          default = null;
          example = "/usr/share/zoneinfo/UTC";
          description = "Absolute path outside the store that this entry links to, in place of `text`.";
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
        kind = mkOption {
          type = types.nullOr (
            types.enum [
              "text"
              "source"
              "target"
            ]
          );
          internal = true;
          readOnly = true;
          description = "Which of `text`, `source` and `target` wins by priority; null on a conflict.";
        };
        content = mkOption {
          type = types.nullOr types.str;
          internal = true;
          readOnly = true;
          description = "The text of a `text` entry; null for other kinds.";
        };
        sourcePath = mkOption {
          type = types.nullOr types.str;
          internal = true;
          readOnly = true;
          description = "The store path of a `source` entry; null for other kinds.";
        };
        trigger = mkOption {
          type = types.nullOr types.str;
          internal = true;
          readOnly = true;
          description = "The value whose change restarts a unit that reads this entry: its text, the text of a source path, a source store string, or its target. Nix reads a source only when a restart trigger uses it.";
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
          defined = lib.filter (kind: config.${kind} != null) [
            "text"
            "source"
            "target"
          ];
          priority = kind: options.${kind}.highestPrio;
          best = lib.foldl' lib.min 1000000 (map priority defined);
          winners = lib.filter (kind: priority kind == best) defined;
          kind = if builtins.length winners == 1 then builtins.head winners else null;
          sourcePath = if kind == "source" then "${config.source}" else null;
        in
        {
          inherit kind sourcePath;
          content = if kind == "text" then config.text else null;
          trigger =
            if kind == "text" then
              config.text
            # A Nix path is read as text, so a trigger sees the same value as
            # for `text`; a store string stays a string, so evaluation never
            # builds a derivation.
            else if kind == "source" then
              if builtins.isPath config.source then builtins.readFile config.source else config.source
            else
              config.target;
          contentError =
            if defined == [ ] then
              "environment.etc.\"${name}\" defines neither text, source nor target"
            else if kind == null then
              "environment.etc.\"${name}\" defines ${
                lib.optionalString (builtins.length winners == 2) "both "
              }${lib.concatStringsSep " and " winners} at the same priority"
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
    description = "Files and symlinks under /etc. Each name is a path relative to /etc.";
  };
}
