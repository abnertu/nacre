# The workstation profile: desktop application settings.
{ pkgs, ... }:
{
  imports = [ ../../modules/home/config-files.nix ];

  home.packages = [ pkgs.cava ];
}
