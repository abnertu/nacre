# Evaluate raw native settings against system-settings-options.nix.
{
  lib,
  raw ? { },
}:
let
  result =
    (lib.evalModules {
      modules = [
        { options = import ./system-settings-options.nix { inherit lib; }; }
        raw
      ];
    }).config;
  hotspotAddressValid =
    if result.hotspot == null then
      true
    else
      let
        parts = lib.splitString "/" result.hotspot.address;
        prefix = builtins.fromJSON (builtins.elemAt parts 1);
        address = lib.foldl' (acc: value: acc * 256 + builtins.fromJSON value) 0 (
          lib.splitString "." (builtins.head parts)
        );
        size = lib.foldl' (acc: _: acc * 2) 1 (lib.range 1 (32 - prefix));
        offset = lib.mod address size;
      in
      offset != 0 && offset != size - 1;
in
assert lib.assertMsg hotspotAddressValid "hotspot requires a usable host address";
assert lib.assertMsg (
  result.hotspot == null || result.hotspot.interface != result.hotspot.uplink
) "hotspot and uplink must differ";
assert lib.assertMsg (
  result.hotspot == null
  || (
    if result.hotspot.band == "bg" then result.hotspot.channel <= 14 else result.hotspot.channel > 14
  )
) "hotspot channel does not match band";
assert lib.assertMsg (
  result.locale == null || builtins.elem result.locale.lang result.locale.generated
) "LANG must be generated";
assert lib.assertMsg (
  result.locale == null || lib.unique result.locale.generated == result.locale.generated
) "duplicate generated locales";
assert lib.assertMsg (
  result.power == null || result.power.powerKey != null || result.power.lidSwitch != null
) "power must select an event";
assert lib.assertMsg (
  result.firewall == null
  || lib.all (r: r.toPort == null || r.toPort >= r.fromPort) result.firewall.rules
) "invalid firewall port range";
assert lib.assertMsg (
  result.firewall == null || lib.unique result.firewall.rules == result.firewall.rules
) "duplicate firewall rules";
builtins.deepSeq result result
