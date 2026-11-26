# Default configuration for the base profile's terminal tools; btop selects
# the theme Noctalia writes when the desktop runs. Sources are defaults:
# a machine's home module replaces one with its own.
{ lib, ... }:
let
  sourceRoot = ../../files/home;
in
{
  xdg.configFile = lib.genAttrs [ "btop" "fastfetch" ] (name: {
    source = (lib.mkOverride 1100) (sourceRoot + "/.config/${name}");
    recursive = (lib.mkOverride 1100) true;
  });
  # Powerlevel10k's prompt; without it p10k starts its configuration wizard.
  home.file.".p10k.zsh".source = (lib.mkOverride 1100) (sourceRoot + "/.p10k.zsh");
}
