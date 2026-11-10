# Capture only reviewed public Runner files. Preserve native relative lookup,
# including directories traversed before `..`; never import a whole directory.
{
  lib,
  root,
  configFiles,
}:
let
  fail = reason: throw "invalid Runner public files: ${reason}";
  join = lib.concatStringsSep "/";
  path = parts: root + "/${join parts}";
  # Each parent has already been checked as a real directory. Inspect the
  # directory entry, not its target, so a symlink cannot escape containment.
  entryType = parts: (builtins.readDir (path (lib.init parts))).${lib.last parts} or "missing";
  resolve =
    parent: reference:
    if !builtins.isString reference || reference == "" || lib.hasPrefix "/" reference then
      fail "references must be nonempty relative paths"
    else
      walk parent (lib.splitString "/" reference) [ ];
  walk =
    parts: remaining: directories:
    let
      component = builtins.head remaining;
      rest = builtins.tail remaining;
      next = parts ++ [ component ];
      kind = entryType next;
    in
    if component == "" || component == "." then
      if rest == [ ] then fail "a file reference ends in a directory" else walk parts rest directories
    else if component == ".." then
      if parts == [ ] then
        fail "a reference escapes the public root"
      else if rest == [ ] then
        fail "a file reference ends in a directory"
      else
        walk (lib.init parts) rest directories
    else if rest == [ ] then
      if kind != "regular" then
        fail "${join next} must be a regular file, found ${kind}"
      else
        {
          file = join next;
          inherit directories;
        }
    else if kind != "directory" then
      fail "${join next} must be a directory, found ${kind}"
    else
      walk next rest (directories ++ [ (join next) ]);
  document = resolved: builtins.fromTOML (builtins.readFile (root + "/${resolved.file}"));
  certificate =
    resolved: doc:
    let
      gitlab = doc.gitlab or { };
    in
    if !builtins.isAttrs gitlab then
      fail "gitlab must be a table"
    else
      lib.optional (gitlab ? ca_certificate) (
        resolve (lib.init (lib.splitString "/" resolved.file)) gitlab.ca_certificate
      );
  dependencies =
    resolved:
    let
      doc = document resolved;
      base = resolve (lib.init (lib.splitString "/" resolved.file)) doc.extends;
      baseDoc = document base;
    in
    [ resolved ]
    ++ certificate resolved doc
    ++ lib.optionals (doc ? extends) (
      if baseDoc ? extends then
        fail "a shared base cannot extend another file"
      else
        [ base ] ++ certificate base baseDoc
    );
  selected = map (resolve [ ]) configFiles;
  names = map (resolved: builtins.baseNameOf resolved.file) selected;
  validNames = lib.all (name: builtins.match "[a-z][a-z0-9-]{0,17}\\.toml" name != null) names;
  closure = lib.concatMap dependencies selected;
  files = lib.unique (map (resolved: resolved.file) closure);
  directories = lib.unique (lib.concatMap (resolved: resolved.directories) closure);
  checked =
    if builtins.readFileType root != "directory" then
      fail "the public root must be a directory"
    else if configFiles == [ ] then
      fail "select at least one instance"
    else if !validNames then
      fail "instance files must use a valid instance name and the .toml suffix"
    else if builtins.length names != builtins.length (lib.unique names) then
      fail "instance names must be unique"
    else
      builtins.deepSeq closure true;
  source =
    assert checked;
    builtins.path {
      name = "runner-public-configuration";
      path = root;
      filter =
        candidate: kind:
        let
          relative = lib.removePrefix "${toString root}/" candidate;
        in
        (kind == "regular" && builtins.elem relative files)
        || (kind == "directory" && (candidate == toString root || builtins.elem relative directories));
    };
in
{
  inherit source;
  configFiles = map (resolved: "${source}/${resolved.file}") selected;
}
