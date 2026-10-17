# Build fixtures through the same entry points as the real deployment.
{ inputs, lib }:
rec {
  modules = extra: [ ./fixtures/configuration.nix ] ++ extra;
  evaluate =
    extra:
    import ../lib/eval-configuration.nix {
      inherit lib;
      modules = modules extra;
    };
  deploy =
    extra:
    import ../lib/mk-deployment.nix {
      inherit inputs;
      modules = modules extra;
    };
  home = extra: username: (deploy extra).homes."${username}@fixture";
  # A second login account with only the named profiles and home modules.
  login =
    {
      homeDirectory,
      profiles ? [ ],
      modules ? [ ],
      development ? { },
    }:
    {
      description = "Fixture login";
      inherit homeDirectory development;
      stateVersion = "26.05";
      profiles = lib.genAttrs (builtins.attrNames (import ../profiles)) (name: {
        enable = builtins.elem name profiles;
      });
      modules = lib.genAttrs (builtins.attrNames (import ../modules/home)) (name: {
        enable = builtins.elem name modules;
      });
    };
}
