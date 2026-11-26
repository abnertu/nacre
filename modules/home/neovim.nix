# Neovim configuration projection into ~/.config/nvim.
{
  config,
  inputs,
  lib,
  pkgs,
  user ? { },
  ...
}:
let
  baseline = import ../../lib/home-baseline.nix lib;
  neovimPath = user.development.neovimPath or null;
  targets = if neovimPath != null then [ ] else [ "nvim" ];
in
{
  imports = [
    (import ./projection-safety.nix {
      inherit targets;
      activationName = "checkNvimProjection";
    })
  ];
  xdg.configFile."nvim" = baseline (
    if neovimPath != null then
      {
        source = config.lib.file.mkOutOfStoreSymlink neovimPath;
      }
    else
      {
        source = if user.sources.neovim or null != null then user.sources.neovim else inputs.nvim-config;
      }
  );

  home.packages = with pkgs; [
    lazygit
    neovim
    tree-sitter
  ];
}
