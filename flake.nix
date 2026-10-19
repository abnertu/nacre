{
  description = "Nacre: declarative Arch Linux + Hyprland, layered with Nix";
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
      url = "github:abnertu/personal-agent";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-adapter = {
      url = "github:abnertu/nix-adapter";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    gitlab-runner = {
      url = "github:abnertu/gitlab-runner";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.nix-adapter.follows = "nix-adapter";
    };
  };

  outputs =
    inputs:
    let
      mkFlake = import ./lib/mk-flake.nix { inherit inputs; };
      mkDeployment = import ./lib/mk-deployment.nix;
      # Checks and the container test use the fixture machine, which enables
      # every feature, so they never depend on any real machine's configuration.
      fixture = ./checks/fixtures/configuration.nix;
      # The fixture also supplies this flake's machine outputs (#nacre,
      # #deployment): the shape every machine flake has, and what CI builds.
      machine = mkFlake { modules = [ fixture ]; };
      d = mkDeployment {
        inherit inputs;
        modules = [ fixture ];
      };
      inherit (d) lib pkgs system;
      # Disables hardware and kernel features a rootless container cannot provide.
      container = mkDeployment {
        inherit inputs;
        modules = [
          fixture
          ./checks/container/configuration.nix
        ];
      };
    in
    lib.recursiveUpdate machine {
      lib = {
        inherit mkFlake;
        container = {
          username = container.host.deployment.username;
          hostname = container.host.name;
          inherit (container.deploymentUser) homeDirectory;
        };
      };

      packages.${system}.container-deployment = container.deployment;
      apps.${system}.just = {
        type = "app";
        program = "${pkgs.just}/bin/just";
        meta.description = "Run development recipes before Home Manager is active";
      };

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
        source-format = import ./checks/format.nix { inherit lib pkgs; };
        source-lint = import ./checks/lint.nix { inherit lib pkgs; };
        python-types = import ./checks/python-types.nix {
          inherit lib pkgs;
          inherit (d) nixAdapter;
        };
        arch-home = d.homes.${d.homeConfigurationName}.activationPackage;
      }
      // (import ./checks {
        inherit lib pkgs;
        inherit (d) arch-switch deploymentName;
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

      formatter.${system} = pkgs.nixfmt;
    };
}
