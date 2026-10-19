{ lib, ... }:
{
  workstation.noctalia.preferencesFile = ./noctalia.toml;
  workstation.fcitx5 = {
    inputMethods = [
      "keyboard-us"
      "chewing"
    ];
    globalOptions.Behavior.PreeditEnabledByDefault = "False";
  };
  programs.git.settings.user.name = lib.mkDefault "Fixture";
}
