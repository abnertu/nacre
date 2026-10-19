{
  description = "A machine managed by Nacre";
  inputs.nacre.url = "github:abnertu/nacre";
  outputs = { nacre, ... }: nacre.lib.mkFlake { modules = [ ./configuration.nix ]; };
}
