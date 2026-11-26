# The hotspot-prepare package that creates the declared AP connection.
{
  pkgs,
  hotspot,
  adapterPython ? pkgs.python3,
}:
pkgs.runCommand "hotspot-prepare"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "hotspot-prepare";
    config = builtins.toJSON {
      inherit hotspot;
      root = "/";
      tty = "/dev/tty";
      requireRoot = true;
      rootOwnership = true;
    };
    passAsFile = [ "config" ];
  }
  ''
    mkdir -p "$out/bin" "$out/share/hotspot-prepare"
    cp "$configPath" "$out/share/hotspot-prepare/config.json"
    makeWrapper ${adapterPython}/bin/python3 "$out/bin/hotspot-prepare" \
      --add-flags "-I ${./prepare_hotspot.py} --config $out/share/hotspot-prepare/config.json"
  ''
