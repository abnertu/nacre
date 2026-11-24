# Machine inputs and configuration modules composed through Nacre.
{
  description = "A machine managed by Nacre";
  inputs.nacre.url = "@url@";
  outputs = { nacre, ... }: nacre.lib.mkFlake { modules = [ ./configuration.nix ]; };
}
