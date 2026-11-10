# Require the published controller in the default flake validation graph.
# Real Runner state lives in a VM; Arch package/core/home boundaries are fixtures.
{ inputs }:
let
  pkgs = inputs.nixpkgs.legacyPackages.x86_64-linux;
  inherit (pkgs) lib;
  controller = inputs.gitlab-runner.packages.x86_64-linux.runnerctl;
  audited = pkgs.writeScriptBin "runnerctl" ''
    #!${pkgs.python3}/bin/python3
    import os
    import sys
    from pathlib import Path
    commands = {"validate", "preflight", "plan", "reconcile", "purge", "register", "verify", "status"}
    command = next((arg for arg in sys.argv[1:] if arg in commands), None)
    if command == "register":
        raise SystemExit("registration is forbidden in the native fixture")
    audit = Path("/run/nacre-native")
    if audit.is_dir():
        with (audit / "controller-calls").open("a") as stream:
            stream.write(str(command) + "\n")
    os.execv("${lib.getExe' controller "runnerctl"}", ["runnerctl", *sys.argv[1:]])
  '';
  deployment = import ../../../lib/mk-deployment.nix {
    inputs = inputs // {
      gitlab-runner.packages.x86_64-linux.runnerctl = audited;
    };
    modules = [
      ../../../checks/fixtures/configuration.nix
      {
        role = "runner";
        services.gitlabRunner.configFiles = [
          ../../../checks/fixtures/runner-native/frontend.toml
          ../../../checks/fixtures/runner-native/dotnet.toml
        ];
      }
    ];
  };
  fixture = pkgs.writeScriptBin "native-fixture" ''
    #!${pkgs.python3}/bin/python3
    import sys
    sys.path.insert(0, "${./.}")
    from native_fixture import main
    main()
  '';
  arch = pkgs.runCommand "native-runner-arch-switch" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    cp -r ${deployment.arch-switch} "$out"
    chmod -R u+w "$out"
    python ${./native_fixture.py} configure \
      "$out/share/arch-switch/config.json" ${fixture}/bin/native-fixture
    substituteInPlace "$out/bin/arch-switch" \
      --replace-fail '${deployment.arch-switch}/share/arch-switch/config.json' "$out/share/arch-switch/config.json"
  '';
  home = pkgs.writeScriptBin "home-switch" ''
    #!${pkgs.python3}/bin/python3
    import sys
    sys.path.insert(0, "${./.}")
    from native_fixture import home
    home()
  '';
  wrapper = import ../../../lib/deployment/package.nix {
    inherit lib pkgs;
    deploymentName = "native-runner-deployment";
    arch-switch = arch;
    home-switch = home;
  };
  # This image tests native manager lifecycle, not the official image contents.
  managerImage = pkgs.dockerTools.buildLayeredImage {
    name = "gitlab/gitlab-runner";
    tag = "v18.10.1";
    contents = [
      pkgs.gitlab-runner
      pkgs.coreutils
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.cacert
    ];
    extraCommands = ''
      mkdir -p etc home/gitlab-runner
      echo 'root:x:0:0:root:/root:/bin/sh' >etc/passwd
      echo 'gitlab-runner:x:999:999:Runner:/home/gitlab-runner:/bin/sh' >>etc/passwd
      echo 'root:x:0:' >etc/group
      echo 'gitlab-runner:x:999:' >>etc/group
    '';
    config.Entrypoint = [ "${pkgs.gitlab-runner}/bin/gitlab-runner" ];
  };
  nativePaths = {
    curl = "${pkgs.curl}/bin/curl";
    env = "${pkgs.coreutils}/bin/env";
    podman = "/run/current-system/sw/bin/podman";
    ip = "${pkgs.iproute2}/bin/ip";
    trust = "${pkgs.p11-kit}/bin/trust";
    useradd = "${pkgs.shadow}/bin/useradd";
    passwd = "${pkgs.shadow}/bin/passwd";
    usermod = "${pkgs.shadow}/bin/usermod";
    runuser = "${pkgs.util-linux}/bin/runuser";
    loginctl = "${pkgs.systemd}/bin/loginctl";
    systemctl = "${pkgs.systemd}/bin/systemctl";
  };
  setup = pkgs.writeText "native-runner-paths.json" (builtins.toJSON nativePaths);
in
pkgs.testers.runNixOSTest {
  name = "native-runner-provisioning";
  nodes.machine = {
    # Execution must not depend on an external registry or GitLab server.
    networking.useDHCP = false;
    networking.dhcpcd.enable = false;
    networking.enableIPv6 = false;
    virtualisation = {
      memorySize = 4096;
      diskSize = 16384;
      cores = 2;
      podman = {
        enable = true;
        defaultNetwork.settings.dns_enabled = true;
      };
    };
    environment.etc."containers/registries.conf".source = lib.mkForce (
      pkgs.writeText "native-registries.conf" ''
        [[registry]]
        prefix = "docker.io"
        location = "127.0.0.1:5000"
        insecure = true
      ''
    );
    services.dockerRegistry.enable = true;
    systemd.services.docker-registry.serviceConfig = {
      StandardOutput = "null";
      StandardError = "null";
    };
    users.users.fixture = {
      isNormalUser = true;
      uid = 1000;
      extraGroups = [ "wheel" ];
      subUidRanges = [ ];
      subGidRanges = [ ];
      autoSubUidGidRange = false;
    };
    security.sudo.wheelNeedsPassword = false;
    environment.systemPackages = [
      pkgs.bash
      pkgs.curl
      pkgs.openssl
      pkgs.python3
      pkgs.skopeo
      pkgs.aardvark-dns
      fixture
      wrapper
      deployment.runnerctl
    ];
    # Keep the vendor source path identical to the Arch platform contract.
    systemd.services."user@".environment.SYSTEMD_UNIT_PATH = "/usr/lib/systemd/user:";
    # NixOS profile paths otherwise expose a second copy of vendor user units.
    systemd.services."user@".serviceConfig.UnsetEnvironment = [
      "XDG_CONFIG_DIRS"
      "XDG_DATA_DIRS"
    ];
    systemd.tmpfiles.rules = [
      "d /usr/bin 0755 root root -"
      "d /usr/lib/podman 0755 root root -"
      "d /usr/lib/systemd/user 0755 root root -"
      "L+ /usr/lib/podman/aardvark-dns - - - - ${pkgs.aardvark-dns}/bin/aardvark-dns"
      "L+ /bin/bash - - - - ${pkgs.bash}/bin/bash"
    ]
    ++ lib.mapAttrsToList (name: target: "L+ /usr/bin/${name} - - - - ${target}") nativePaths;
  };
  testScript = ''
    import runpy
    runpy.run_path("${./native_test.py}")["run"](machine, "${setup}", "${fixture}/bin/native-fixture", "${managerImage}", "${deployment.runnerctl}/bin/runnerctl")
  '';
}
