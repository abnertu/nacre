# The development profile: Neovim, GitHub CLI, Node.js and pass.
{ lib, pkgs, ... }:
{
  imports = [ ../../modules/home/neovim.nix ];

  home.packages = with pkgs; [
    gh
    git-credential-manager
    nodejs
    nix-output-monitor
  ];

  programs.password-store = import ../../lib/home-baseline.nix lib {
    enable = true;
    package = pkgs.pass;
  };
}
