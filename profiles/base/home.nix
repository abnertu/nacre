{
  config,
  lib,
  pkgs,
  ...
}:
{
  imports = [ ../../modules/home/shell-files.nix ];

  home.sessionPath = [
    "$HOME/.local/bin"
    "$HOME/go/bin"
    "$HOME/.luarocks/bin"
  ];

  home.packages = with pkgs; [
    bat
    bc
    btop
    cava
    chafa
    curl
    eza
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
        core = {
          autocrlf = lib.mkDefault false;
          filemode = lib.mkDefault false;
          fsmonitor = lib.mkDefault false;
          ignorecase = lib.mkDefault true;
          longpaths = lib.mkDefault true;
          quotePath = lib.mkDefault false;
          symlinks = lib.mkDefault true;
        };
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
        expireDuplicatesFirst = lib.mkDefault true;
        ignoreAllDups = lib.mkDefault true;
        ignoreDups = lib.mkDefault true;
        ignoreSpace = lib.mkDefault true;
        save = lib.mkDefault 10000;
        share = lib.mkDefault true;
        size = lib.mkDefault 10000;
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
      initContent = lib.mkOrder 1000 ''
        source ${pkgs.zsh-powerlevel10k}/share/zsh-powerlevel10k/powerlevel10k.zsh-theme
        [[ -r ${config.home.homeDirectory}/.p10k.zsh ]] && source ${config.home.homeDirectory}/.p10k.zsh
        bindkey '^K' autosuggest-accept
      '';
    };
  };
}
