# Each role is a baseline below host defaults: roles set values at priority
# 1100, hosts at lib.mkDefault (1000), the operator's configuration above both.
{ config, lib, ... }:
let
  baseline = lib.mapAttrsRecursive (_: lib.mkOverride 1100);
  roles = {
    # The option defaults: core system, shell and development tools.
    minimal = { };
    workstation = {
      desktop.enable = true;
      programs = {
        sunshine.enable = true;
        vesktop.enable = true;
        vicinae.enable = true;
      };
    };
  };
in
{
  options.role = lib.mkOption {
    type = lib.types.enum (builtins.attrNames roles);
    default = "workstation";
    description = "Baseline composition: minimal (no graphical session) or workstation.";
  };
  config = lib.mkMerge (
    lib.mapAttrsToList (name: values: lib.mkIf (config.role == name) (baseline values)) roles
  );
}
