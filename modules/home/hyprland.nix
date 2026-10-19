{
  config,
  inputs,
  user ? { },
  ...
}:
let
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
  xdg.configFile."hypr" =
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
      };

  home.file.".zprofile".text = ''
    if ${uwsm} check may-start; then
      exec ${uwsm} start hyprland.desktop
    fi
  '';
}
