# Application dotfiles, projected read-only from ./files.
{
  lib,
  capabilities,
  hardware,
  ...
}:
let
  sourceRoot = ./files;
  configDirectories = [
    "btop"
    "cava"
    "fastfetch"
    "ghostty"
    "kitty"
    "onedrive"
    "swappy"
  ]
  ++ lib.optional hardware.openrazer "openrazer"
  ++ lib.optionals capabilities.programs.vesktop.enable [
    "vesktop/settings"
  ];
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
      "gtk-3.0/bookmarks".source = sourceRoot + "/.config/gtk-3.0/bookmarks";
      "polychromatic/preferences.json" = lib.mkIf hardware.openrazer {
        source = sourceRoot + "/.config/polychromatic/preferences.json";
      };
      "sunshine/sunshine.conf" = lib.mkIf capabilities.programs.sunshine.enable {
        source = sourceRoot + "/.config/sunshine/sunshine.conf";
      };
      "vesktop/settings.json" = lib.mkIf capabilities.programs.vesktop.enable {
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
