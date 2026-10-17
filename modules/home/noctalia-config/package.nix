{
  pkgs,
  adapterPython,
  username,
  homeConfiguration,
}:
pkgs.writeShellApplication {
  name = "noctalia-config";
  runtimeInputs = [
    pkgs.git
  ];
  text = ''
    exec ${adapterPython}/bin/python ${./sync.py} \
      --user ${pkgs.lib.escapeShellArg username} \
      --home-configuration ${pkgs.lib.escapeShellArg homeConfiguration} "$@"
  '';
}
