# Nacre configuration for @hostname@, written by `nacre install`.
# Plain definitions here override the role baseline and module defaults;
# docs/configuration.md lists what can be changed.
{ ... }:
{
  role = "@role@";
  networking.hostname.name = "@hostname@";
  time.timeZone = "@timezone@";
  i18n = {
    generated = [ "@locale@" ];
    lang = "@locale@";
  };

  deployment.username = "@username@";
  users.users.@username@ = {
    description = "@description@";
    homeDirectory = "/home/@username@";
    stateVersion = "26.05";
    admin = true;
  };

  hardware = {
    graphics = "@graphics@";
    initramfs.images = [ @images@ ];
  };
}
