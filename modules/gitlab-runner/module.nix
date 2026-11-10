# Runner owns native instance state; this module owns only its Arch wiring.
{
  config,
  lib,
  runnerctl,
  ...
}:
let
  cfg = config.services.gitlabRunner;
  public = import ./interface.nix {
    inherit lib;
    inherit (cfg) configFiles;
  };
in
{
  options.services.gitlabRunner = {
    enable = lib.mkEnableOption "deployment of the declared GitLab Runner instances";
    configFiles = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      description = ''
        Public instance TOML files, named after their instances.
        The first file's directory bounds all selected files, shared bases and relative CA certificates.
        Declared files expose the configured runnerctl output independently of deployment enablement.
      '';
    };
  };

  config.arch = lib.mkIf cfg.enable {
    # Shared container packages remain with virtualization.
    pacman = [ "slirp4netns" ];
    extensions.gitlab-runner = {
      label = "GitLab Runner";
      adapter = ./adapter.py;
      manifest = {
        executable = "${runnerctl}/bin/runnerctl";
        inherit (public) instances;
      };
      purge = true;
    };
  };
}
