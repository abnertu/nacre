{ pkgs, ... }:
{
  imports = [ ../../modules/home/neovim.nix ];

  home.packages = with pkgs; [
    gh
    git-credential-manager
    nodejs
    nix-output-monitor
  ];

  programs.password-store = {
    enable = true;
    package = pkgs.pass;
  };
}
