# The base profile: shell, Git and command-line tools for every account.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  # Priority 1100: a machine's plain definition or lib.mkDefault replaces it.
  baseline = lib.mkOverride 1100;
in
{
  imports = [ ../../modules/home/shell-files.nix ];

  home.sessionPath = [ "$HOME/.local/bin" ];

  home.packages = with pkgs; [
    bat
    bc
    btop
    chafa
    curl
    fastfetch
    fd
    gum
    jq
    just
    lsd
    p7zip
    ripgrep
    rsync
    tldr
    unzip
    wget
  ];

  # Apply defaults to individual options: submodules and initialization fragments
  # must still merge with Home Manager's generated definitions.
  programs = {
    fzf = {
      enable = baseline true;
      enableZshIntegration = baseline true;
    };

    git = {
      enable = baseline true;
      settings = {
        # Show non-ASCII file names as they are.
        core.quotePath = baseline false;
        diff.algorithm = baseline "histogram";
        fetch.prune = baseline true;
        init.defaultBranch = baseline "main";
        merge.conflictStyle = baseline "zdiff3";
        pull.rebase = baseline true;
        rebase.autoStash = baseline true;
      };
    };

    zsh = {
      enable = baseline true;
      autosuggestion.enable = baseline true;
      enableCompletion = baseline true;
      syntaxHighlighting.enable = baseline true;
      history = {
        ignoreAllDups = baseline true;
        ignoreSpace = baseline true;
        save = baseline 50000;
        share = baseline true;
        size = baseline 50000;
      };
      shellAliases = {
        l = baseline "lsd -l";
        la = baseline "lsd -a";
        ll = baseline "lsd -al";
        lt = baseline "lsd --tree";
        v = baseline "nvim";
      };
      oh-my-zsh = {
        enable = baseline true;
        plugins = [ "git" ];
      };
      initContent = lib.mkMerge [
        # Powerlevel10k's instant prompt must come first in .zshrc: the prompt
        # appears at once while the rest of the configuration loads.
        (lib.mkOrder 500 ''
          if [[ -r "''${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-''${(%):-%n}.zsh" ]]; then
            source "''${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-''${(%):-%n}.zsh"
          fi
        '')
        (lib.mkOrder 1000 ''
          source ${pkgs.zsh-powerlevel10k}/share/zsh-powerlevel10k/powerlevel10k.zsh-theme
          [[ -r ${config.home.homeDirectory}/.p10k.zsh ]] && source ${config.home.homeDirectory}/.p10k.zsh
          bindkey '^K' autosuggest-accept
        '')
      ];
    };
  };
}
