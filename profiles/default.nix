# Home profiles that a login account enables by name. Each entry is the module
# and the one-line description its enable option shows.
{
  base = {
    module = ./base/home.nix;
    description = "the base shell, Git and command-line tools";
  };
  dev = {
    module = ./dev/home.nix;
    description = "the development tools: Neovim, GitHub CLI, Node.js and pass";
  };
  workstation = {
    module = ./workstation/home.nix;
    description = "the desktop application settings; it applies only when the desktop is enabled";
  };
}
