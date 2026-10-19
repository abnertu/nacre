# Desktop files every workstation shares: toolkit theming that follows
# Noctalia's palette and Electron's Wayland flags. Personal dotfiles come from
# the user's own home modules.
{ config, ... }:
let
  sourceRoot = ../../files/home;
  # qt5ct and qt6ct need an absolute path to the palette Noctalia generates.
  qtConfig =
    version:
    builtins.replaceStrings [ "@configHome@" ] [ config.xdg.configHome ] (
      builtins.readFile (sourceRoot + "/.config/qt${version}ct/qt${version}ct.conf")
    );
in
{
  xdg.configFile =
    builtins.listToAttrs (
      map
        (name: {
          inherit name;
          value = {
            source = sourceRoot + "/.config/${name}";
            recursive = true;
          };
        })
        [
          "gtk-3.0"
          "gtk-4.0"
          "quickshell"
        ]
    )
    // {
      "qt5ct/qt5ct.conf".text = qtConfig "5";
      "qt6ct/qt6ct.conf".text = qtConfig "6";
      "electron-flags.conf".source = sourceRoot + "/.config/electron-flags.conf";
    };
}
