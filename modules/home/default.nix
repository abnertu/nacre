# Home modules that a login account enables by name. Each entry is the module
# and the one-line description its enable option shows.
{
  graphical-session = {
    module = ./graphical-session.nix;
    description = "the systemd user services of the Hyprland session";
  };
  hyprland = {
    module = ./hyprland.nix;
    description = "the Hyprland configuration and its UWSM entry point";
  };
  noctalia-storage = {
    module = ./noctalia-storage.nix;
    description = "Noctalia's file-based key storage";
  };
  noctalia-config = {
    module = ./noctalia-config;
    description = "the reviewed Noctalia preferences and the noctalia sync tool";
  };
}
