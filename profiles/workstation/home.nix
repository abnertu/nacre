{ pkgs, ... }:
{
  imports = [ ../../modules/home/config-files.nix ];

  home.packages = [ pkgs.cava ];
}
