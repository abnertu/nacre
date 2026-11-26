# Hyprland configuration projection and its UWSM entry point.
{
  config,
  inputs,
  lib,
  user ? { },
  ...
}:
let
  baseline = import ../../lib/home-baseline.nix lib;
  uwsm = "/usr/bin/uwsm";
  hyprlandPath = user.development.hyprlandPath or null;
  targets = if hyprlandPath != null then [ ] else [ "hypr" ];
in
{
  imports = [
    (import ./projection-safety.nix {
      inherit targets;
      activationName = "checkHyprProjection";
    })
  ];
  xdg.configFile."hypr" = baseline (
    if hyprlandPath != null then
      {
        source = config.lib.file.mkOutOfStoreSymlink hyprlandPath;
        recursive = false;
      }
    else
      {
        source =
          if user.sources.hyprland or null != null then user.sources.hyprland else inputs.hypr-config;
        recursive = true;
      }
  );

  # Lines: a machine's .zprofile text adds to this start.
  home.file.".zprofile".text = ''
    if ${uwsm} check may-start; then
      exec ${uwsm} start hyprland.desktop
    fi
  '';
}
