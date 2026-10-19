# Default desktop configuration: the terminal, toolkit theming that follows
# Noctalia's palette, Electron's Wayland flags and the Quickshell overview.
# Sources are defaults: a machine's home module replaces one with its own.
{
  config,
  lib,
  capabilities,
  ...
}:
let
  sourceRoot = ../../files/home;
  directory = name: {
    source = lib.mkDefault (sourceRoot + "/.config/${name}");
    recursive = lib.mkDefault true;
  };
  file = name: { source = lib.mkDefault (sourceRoot + "/.config/${name}"); };
  # qt5ct and qt6ct need an absolute path to the palette Noctalia generates.
  qtConfig =
    version:
    builtins.replaceStrings [ "@configHome@" ] [ config.xdg.configHome ] (
      builtins.readFile (sourceRoot + "/.config/qt${version}ct/qt${version}ct.conf")
    );
in
{
  xdg.configFile = lib.genAttrs [ "ghostty" "gtk-3.0" "gtk-4.0" "quickshell" "swappy" ] directory // {
    "qt5ct/qt5ct.conf".text = lib.mkDefault (qtConfig "5");
    "qt6ct/qt6ct.conf".text = lib.mkDefault (qtConfig "6");
    "electron-flags.conf" = file "electron-flags.conf";
    "vesktop/settings.json" = lib.mkIf capabilities.programs.vesktop.enable (
      file "vesktop/settings.json"
    );
    "vesktop/settings/settings.json" = lib.mkIf capabilities.programs.vesktop.enable (
      file "vesktop/settings/settings.json"
    );
  };
}
