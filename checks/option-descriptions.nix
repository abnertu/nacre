# Every option that Nacre declares carries its own description: no option is
# undocumented, and no two different options share one text (a copied or
# placeholder description). It reads the option doc lists only; a recursive
# walk through `type.getSubOptions` does not terminate on the Home Manager tree.
{
  lib,
  pkgs,
  nacreOptions,
  homeOptions,
}:
let
  # Option sets that one declaration reuses under several paths. A field of
  # such a set may repeat its text across the prefixes of one group.
  reusedSets = [
    [
      [
        "programs"
        "ai"
        "llama"
        "model"
      ]
      [
        "programs"
        "ai"
        "llama"
        "models"
        "<name>"
      ]
      [
        "programs"
        "ai"
        "llama"
        "profiles"
        "<name>"
      ]
    ]
  ];

  isPrefix = prefix: loc: lib.take (builtins.length prefix) loc == prefix;

  # Children of an internal option stay visible in the doc list; drop them too.
  visibleOptions =
    entries:
    let
      internal = map (entry: entry.loc) (builtins.filter (entry: entry.internal) entries);
    in
    builtins.filter (
      entry: !entry.internal && !(builtins.any (prefix: isPrefix prefix entry.loc) internal)
    ) entries;

  nacreEntries = builtins.filter (entry: builtins.head entry.loc != "_module") (
    lib.optionAttrSetToDocList nacreOptions
  );
  homeEntries = builtins.filter (entry: builtins.head entry.loc == "workstation") (
    lib.optionAttrSetToDocList homeOptions
  );
  entries = visibleOptions nacreEntries ++ visibleOptions homeEntries;

  text = entry: if entry.description == null then "" else lib.trim entry.description;

  undocumented = map (entry: entry.name) (builtins.filter (entry: text entry == "") entries);

  # The field path of `loc` below the reused set that contains it, if any.
  reusedField =
    loc:
    let
      matches = lib.concatMap (
        group:
        map (prefix: lib.drop (builtins.length prefix) loc) (
          builtins.filter (prefix: isPrefix prefix loc) group
        )
      ) reusedSets;
    in
    if matches == [ ] then null else builtins.head matches;

  sameOption =
    left: right:
    left.loc == right.loc
    || reusedField left.loc == reusedField right.loc && reusedField left.loc != null;

  byText = lib.groupBy text (builtins.filter (entry: text entry != "") entries);
  shared = lib.concatMap (
    group:
    let
      first = builtins.head group;
    in
    lib.optional (builtins.any (entry: !sameOption first entry) group) (
      "\"${text first}\": " + lib.concatMapStringsSep ", " (entry: entry.name) group
    )
  ) (builtins.attrValues byText);

  report = lib.concatStringsSep "\n" (
    lib.optionals (undocumented != [ ]) ([ "Options without a description:" ] ++ undocumented)
    ++ lib.optionals (shared != [ ]) ([ "One description on different options:" ] ++ shared)
  );
in
pkgs.runCommand "option-descriptions"
  {
    passAsFile = [ "report" ];
    inherit report;
  }
  ''
    if [ -s "$reportPath" ]; then
      cat "$reportPath" >&2
      exit 1
    fi
    touch "$out"
  ''
