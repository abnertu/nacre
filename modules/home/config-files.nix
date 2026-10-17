{
  config,
  lib,
  capabilities,
  hardware,
  ...
}:
let
  sourceRoot = ../../files/home;
  configDirectories = [
    "btop"
    "cava"
    "fastfetch"
    "ghostty"
    "gtk-3.0"
    "gtk-4.0"
    "kitty"
    "onedrive"
    "quickshell"
    "swappy"
  ]
  ++ lib.optional hardware.openrazer "openrazer"
  ++ lib.optionals capabilities.programs.vesktop.enable [
    "vesktop/settings"
  ];
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
      map (name: {
        inherit name;
        value = {
          source = sourceRoot + "/.config/${name}";
          recursive = true;
        };
      }) configDirectories
    )
    // {
      "qt5ct/qt5ct.conf".text = qtConfig "5";
      "qt6ct/qt6ct.conf".text = qtConfig "6";
      "electron-flags.conf".source = sourceRoot + "/.config/electron-flags.conf";
      "polychromatic/preferences.json" = lib.mkIf (hardware.openrazer) {
        source = sourceRoot + "/.config/polychromatic/preferences.json";
      };
      "sunshine/sunshine.conf" = lib.mkIf (capabilities.programs.sunshine.enable) {
        source = sourceRoot + "/.config/sunshine/sunshine.conf";
      };
      "vesktop/settings.json" = lib.mkIf (capabilities.programs.vesktop.enable) {
        source = sourceRoot + "/.config/vesktop/settings.json";
      };
    };

  home.file = {
    "AGENTS.md".source = sourceRoot + "/AGENTS.md";
    ".p10k.zsh".source = sourceRoot + "/.p10k.zsh";
    "Pictures/Wallpapers" = {
      source = sourceRoot + "/Pictures/Wallpapers";
      recursive = true;
    };
  };
}
