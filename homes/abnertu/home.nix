{
  lib,
  pkgs,
  ...
}:
{
  config = lib.mkDefault {
    workstation.noctalia.preferencesFile = ./noctalia/config.toml;

    programs.git.settings = {
      user = {
        email = "qw0207060413@gmail.com";
        name = "abner";
      };
      credential = {
        credentialStore = "gpg";
        helper = "${pkgs.git-credential-manager}/bin/git-credential-manager";
      };
      "credential \"https://dev.azure.com\"".useHttpPath = true;
      "credential \"https://github.com\"".useHttpPath = false;
      "credential \"https://gitlab.com\"".useHttpPath = false;
      interactive.diffFilter = "${pkgs.delta}/bin/delta --color-only";
    };

    programs.delta = {
      enable = true;
      enableGitIntegration = true;
      options = {
        dark = true;
        line-numbers = true;
        navigate = true;
        side-by-side = true;
      };
    };
  };
}
