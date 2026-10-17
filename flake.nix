{
  description = "Arch workstation deployment and Home Manager configuration";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nvim-config = {
      url = "github:Orbit-Lua/orbitvim";
      flake = false;
    };

    hypr-config = {
      url = "github:Orbit-Lua/hypr";
      flake = false;
    };

    matt-pocock-skills = {
      url = "github:mattpocock/skills";
      flake = false;
    };

    vercel-skills = {
      url = "github:vercel-labs/skills";
      flake = false;
    };

    personal-agent = {
      url = "github:gin31259461/personal-agent";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-adapter = {
      url = "github:gin31259461/nix-adapter";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    gitlab-runner = {
      url = "github:gin31259461/gitlab-runner";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.nix-adapter.follows = "nix-adapter";
    };
  };

  outputs =
    inputs:
    let
      mkDeployment = import ./lib/mk-deployment.nix;
      d = mkDeployment { inherit inputs; };
      inherit (d) lib pkgs system;
    in
    {
      homeConfigurations = d.homes;
      # This is a queryable normalized configuration, not a NixOS system.
      lib.configurations.arch = d.configuration.config;
      lib.runnerctlEnabled = d.runners.packages != { };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (pkgs.python3.withPackages (pythonPackages: [
            pythonPackages.jinja2
            pythonPackages.rich
            d.nixAdapter
          ]))
          pkgs.pyright
          pkgs.ruff
          pkgs.just
          pkgs.nix-output-monitor
          pkgs.nixfmt
        ];
      };

      checks.${system} = {
        configuration = import ./checks/configuration.nix { inherit lib pkgs inputs; };
        capabilities = import ./checks/capabilities.nix { inherit lib pkgs inputs; };
        optional-modules = import ./checks/optional-modules.nix { inherit lib pkgs inputs; };
        source-format = import ./checks/format.nix { inherit lib pkgs; };
        python-types = import ./checks/python-types.nix {
          inherit lib pkgs;
          inherit (d) nixAdapter;
        };
        arch-home = d.homes.${d.homeConfigurationName}.activationPackage;
      }
      // (import ./checks {
        inherit lib pkgs;
        inherit (d) arch-switch deploymentName adapterPython;
        archDeployment = d.deployment;
      })
      // (import ./platforms/arch/checks.nix {
        inherit pkgs;
        inherit (d) arch-switch llama-prepare adapterPython;
        aiManifest = d.archAi.manifest;
      })
      // (import ./modules/home/checks.nix {
        inherit pkgs inputs;
        inherit (d) adapterPython;
        home = d.homes.${d.homeConfigurationName};
        user = d.deploymentUser;
      })
      // d.runners.checks;

      packages.${system} = {
        inherit (d) arch-switch home-switch llama-prepare;
        ${d.deploymentName} = d.deployment;
        default = d.arch-switch;
      }
      // lib.optionalAttrs d.noctaliaEnabled { inherit (d) noctalia-config; }
      // d.runners.packages;

      apps.${system} = {
        llama-prepare = {
          type = "app";
          program = "${d.llama-prepare}/bin/llama-prepare";
          meta.description = "Explicitly prepare the pinned llama.cpp build and model";
        };
        arch-switch = {
          type = "app";
          program = "${d.arch-switch}/bin/arch-switch";
          meta.description = "Converge Arch-native workstation policy";
        };
        ${d.deploymentName} = {
          type = "app";
          program = "${d.deployment}/bin/${d.deploymentName}";
          meta.description = "Build and activate ${d.deploymentName}";
        };
        home-switch = {
          type = "app";
          program = "${d.home-switch}/bin/home-switch";
          meta.description = "Activate ${d.homeConfigurationName} through Home Manager";
        };
        just = {
          type = "app";
          program = "${pkgs.just}/bin/just";
          meta.description = "Run project commands before Home Manager is active";
        };
      }
      // lib.optionalAttrs d.noctaliaEnabled {
        noctalia-config = {
          type = "app";
          program = "${d.noctalia-config}/bin/noctalia-config";
          meta.description = "Capture or deploy reviewed Noctalia preferences";
        };
      }
      // d.runners.apps;

      formatter.${system} = pkgs.nixfmt;
    };
}
