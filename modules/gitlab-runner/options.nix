{ lib }:
{
  enable = (lib.mkEnableOption "the declared GitLab Runner instances") // {
    default = true;
  };
  configFiles = lib.mkOption {
    type = lib.types.listOf lib.types.path;
    default = [ ];
    description = ''
      Runner instance files, each named after the environment it serves
      (`frontend.toml` declares `frontend`). runnerctl validates the whole set;
      bases named by `extends` and relative CA certificates are included.
    '';
  };
}
