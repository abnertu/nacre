{
  config,
  lib,
  pkgs,
  ...
}:
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
      enable = lib.mkDefault true;
      enableZshIntegration = lib.mkDefault true;
    };

    git = {
      enable = lib.mkDefault true;
      settings = {
        # Show non-ASCII file names as they are.
        core.quotePath = lib.mkDefault false;
        diff.algorithm = lib.mkDefault "histogram";
        fetch.prune = lib.mkDefault true;
        init.defaultBranch = lib.mkDefault "main";
        merge.conflictStyle = lib.mkDefault "zdiff3";
        pull.rebase = lib.mkDefault true;
        rebase.autoStash = lib.mkDefault true;
      };
    };

    zsh = {
      enable = lib.mkDefault true;
      autosuggestion.enable = lib.mkDefault true;
      enableCompletion = lib.mkDefault true;
      syntaxHighlighting.enable = lib.mkDefault true;
      history = {
        ignoreAllDups = lib.mkDefault true;
        ignoreSpace = lib.mkDefault true;
        save = lib.mkDefault 50000;
        share = lib.mkDefault true;
        size = lib.mkDefault 50000;
      };
      shellAliases = {
        l = lib.mkDefault "lsd -l";
        la = lib.mkDefault "lsd -a";
        ll = lib.mkDefault "lsd -al";
        lt = lib.mkDefault "lsd --tree";
        v = lib.mkDefault "nvim";
      };
      oh-my-zsh = {
        enable = lib.mkDefault true;
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
