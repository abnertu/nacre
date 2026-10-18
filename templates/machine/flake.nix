{
  description = "A machine managed by Nacre";
  inputs.nacre.url = "github:gin31259461/nacre";
  outputs = { nacre, ... }: nacre.lib.mkFlake { modules = [ ./configuration.nix ]; };
}
