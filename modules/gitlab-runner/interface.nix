# Keep the existing declaration boundary: the first instance's directory.
{ lib, configFiles }:
let
  fail = reason: throw "invalid Runner configuration: ${reason}";
  root = builtins.dirOf (builtins.head configFiles);
  prefix = "${toString root}/";
  relative = file: lib.removePrefix prefix (toString file);
  contained = lib.all (file: lib.hasPrefix prefix (toString file)) configFiles;
  public = import ./public-files.nix {
    inherit lib root;
    configFiles = map relative configFiles;
  };
in
if configFiles == [ ] then
  fail "select at least one instance"
else if !contained then
  fail "instance files must stay under the first instance's directory"
else
  {
    inherit root;
    configFiles = map relative configFiles;
    # Force the selective closure only when this interface is selected.
    instances = builtins.seq public.source (
      builtins.sort builtins.lessThan (
        map (file: lib.removeSuffix ".toml" (builtins.baseNameOf file)) configFiles
      )
    );
  }
