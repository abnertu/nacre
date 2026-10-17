{
  lib,
  pkgs,
  rawInstances ? { },
  gitlab-runner ? null,
  ...
}:
let
  enabled = rawInstances != { };
  instances = import ./interface.nix { inherit lib rawInstances; };
  platform = import ./arch-platform.nix;
  controller = import ./package.nix {
    inherit
      pkgs
      instances
      gitlab-runner
      platform
      ;
  };
in
{
  packages = lib.optionalAttrs enabled { runnerctl = controller; };
  apps = lib.optionalAttrs enabled {
    runnerctl = {
      type = "app";
      program = "${controller}/bin/runnerctl";
      meta.description = "Manage dedicated rootless GitLab Runner instances";
    };
  };
  checks = {
    gitlab-runner-interface =
      assert import ./tests/interface.nix { inherit lib; };
      pkgs.writeText "gitlab-runner-interface" "passed";
  }
  // lib.optionalAttrs enabled {
    gitlab-runner-config = pkgs.runCommand "gitlab-runner-config-check" { } ''
      ${controller}/bin/runnerctl validate > "$out"
    '';
  };
}
