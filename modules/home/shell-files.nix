# Default configuration for the base profile's terminal tools; btop and cava
# select the theme Noctalia writes when the desktop runs. Sources are defaults:
# a machine's home module replaces one with its own.
{ lib, ... }:
let
  sourceRoot = ../../files/home;
in
{
  xdg.configFile = lib.genAttrs [ "btop" "cava" "fastfetch" ] (name: {
    source = lib.mkDefault (sourceRoot + "/.config/${name}");
    recursive = lib.mkDefault true;
  });
  # Powerlevel10k's prompt; without it p10k starts its configuration wizard.
  home.file.".p10k.zsh".source = lib.mkDefault (sourceRoot + "/.p10k.zsh");
}
