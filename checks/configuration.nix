{
  lib,
  pkgs,
  inputs,
}:
let
  fixtures = import ./lib.nix { inherit inputs lib; };
  inherit (fixtures) evaluate;
  base = evaluate [ ];
  disabledModule = {
    networking.firewall.enable = false;
    networking.networkmanager.enable = false;
    hardware.bluetooth.enable = false;
    programs.ai.enable = false;
    programs.sunshine.enable = false;
    programs.vesktop.enable = false;
    programs.vicinae.enable = false;
    virtualization.enable = false;
    services.tailscale.enable = false;
    services.timesyncd.enable = false;
    services.journald.enable = false;
    services.logind.enable = false;
    services.fstrim.enable = false;
    services.powerProfilesDaemon.enable = false;
    services.powerpanel.enable = false;
    console.enable = false;
    time.enable = false;
    i18n.enable = false;
    users.users.fixture.modules.noctalia-config.enable = false;
    hardware.graphics = "generic";
    hardware.openrazer.enable = false;
  };
  disabled = evaluate [ disabledModule ];
  packages = disabled.config.arch;
  # Every optional capability off still builds a deployment and a minimal home.
  minimal = fixtures.deploy [
    disabledModule
    (
      { lib, ... }:
      {
        users.users.fixture = {
          modules.hyprland.enable = false;
          modules.noctalia-storage.enable = false;
          homeModules = lib.mkForce [ ];
        };
      }
    )
  ];
  home = fixtures.home [ disabledModule ] "fixture";
  # What `nacre install` writes for a new machine, without this host's defaults.
  freshInstall = import ../lib/mk-deployment.nix {
    inherit inputs;
    modules = [
      (builtins.toFile "configuration.nix" (
        builtins.replaceStrings
          [
            "@role@"
            "@hostname@"
            "@timezone@"
            "@locale@"
            "@username@"
            "@description@"
            "@graphics@"
            "@images@"
          ]
          [
            "workstation"
            "box"
            "UTC"
            "en_US.UTF-8"
            "alice"
            "Alice"
            "generic"
            ''"/boot/initramfs-linux.img"''
          ]
          (builtins.readFile ../templates/machine/configuration.nix)
      ))
    ];
  };
  # The minimal role alone drops the graphical session; host defaults beat roles.
  minimalRole = fixtures.deploy [ { role = "minimal"; } ];
  roleBelowHost = evaluate [ { desktop.enable = lib.mkDefault false; } ];
  overrideModule = (
    { lib, ... }:
    {
      networking.hostname.name = "overridden";
      time.timeZone = "UTC";
      networking.firewall.rules = lib.mkForce [ ];
      users.users.fixture.home = {
        programs.git.enable = false;
        home.packages = [ pkgs.hello ];
      };
    }
  );
  override = evaluate [ overrideModule ];
  headlessHome = fixtures.home [ { desktop.enable = false; } ] "fixture";
  overriddenHome = (fixtures.deploy [ overrideModule ]).homes."fixture@overridden";
  enablePaths =
    path: value:
    if builtins.isAttrs value then
      lib.concatLists (
        lib.mapAttrsToList (
          name: child:
          if name == "enable" && child then
            [ (path ++ [ name ]) ]
          else if name == "home" then
            [ ]
          else
            enablePaths (path ++ [ name ]) child
        ) value
      )
    else
      [ ];
  allSwitches = enablePaths [ ] base.config;
  switchesWork = lib.all (
    path:
    let
      extra = lib.setAttrByPath path false;
      result = evaluate [
        (lib.recursiveUpdate extra (
          lib.optionalAttrs (
            path == [
              "users"
              "users"
              "fixture"
              "profiles"
              "workstation"
              "enable"
            ]
          ) { role = "minimal"; }
        ))
      ];
    in
    lib.getAttrFromPath path base.config
    && !(lib.getAttrFromPath path result.config)
    && builtins.deepSeq result.host true
  ) allSwitches;
  merged = evaluate [
    {
      imports = [
        {
          networking.firewall.rules = [
            {
              protocol = "tcp";
              fromPort = 1234;
            }
          ];
        }
      ];
    }
    {
      networking.firewall.rules = [
        {
          protocol = "udp";
          fromPort = 1234;
        }
      ];
    }
  ];
  valid = module: (builtins.tryEval (builtins.deepSeq (evaluate [ module ]).host true)).success;
  hotspotOff = evaluate [ { networking.hotspot.enable = false; } ];
  hotspotParentOff = evaluate [
    {
      networking.hotspot.enable = true;
      networking.networkmanager.enable = false;
    }
  ];
  hotspotOverride = evaluate [
    {
      networking.hotspot = {
        enable = true;
        channel = 149;
      };
    }
  ];

in
assert hotspotOverride.host.systemSettings.hotspot.channel == 149;
assert hotspotOff.host.systemSettings.hotspot == null;
assert hotspotParentOff.host.systemSettings.hotspot == null;
assert switchesWork;
assert minimalRole.deploymentName == "fixture-minimal";
assert !minimalRole.configuration.config.desktop.enable;
assert !(builtins.elem "hyprland" minimalRole.configuration.config.arch.pacman);
assert builtins.elem "hyprland" base.config.arch.pacman;
assert !(minimalRole.homes."fixture@fixture".config.home.file ? ".zprofile");
assert !roleBelowHost.config.desktop.enable;
assert builtins.length merged.host.systemSettings.firewall.rules == 2;
assert override.host.name == "overridden" && override.host.systemSettings.timeZone == "UTC";
assert override.host.systemSettings.firewall.rules == [ ];
assert !disabled.host.powerpanel.enable;
assert !(builtins.elem "powerpanel" packages.aur);
assert !overriddenHome.config.programs.git.enable;
assert builtins.elem pkgs.hello overriddenHome.config.home.packages;
assert headlessHome.config.systemd.user.services == { };
assert !(headlessHome.config.home.file ? ".zprofile");
assert !(headlessHome.config.xdg.configFile ? "noctalia/storage.toml");
assert lib.all (name: disabled.host.systemSettings.${name} == null) [
  "firewall"
  "locale"
  "timeZone"
  "timeSync"
  "journal"
  "power"
  "trim"
  "console"
];
assert lib.all (name: !(builtins.elem name packages.pacman)) [
  "ufw"
  "networkmanager"
  "bluez"
  "tailscale"
  "power-profiles-daemon"
];
assert packages.lizardbyte == [ ];
assert !(builtins.elem "vesktop-bin" packages.aur) && !(builtins.elem "vicinae-bin" packages.aur);
assert lib.all (name: !(builtins.hasAttr name home.config.systemd.user.services)) [
  "vesktop"
  "vicinae"
  "tailscale-systray"
];
assert home.config.systemd.user.services.noctalia.Unit.Wants == [ ];
assert !(builtins.hasAttr "noctalia/config.toml" home.config.xdg.configFile);
assert lib.all (homeDirectory: !(valid { users.users.fixture = { inherit homeDirectory; }; })) [
  "/home/"
  "/home/../outside"
  "/home/user/../other"
  "/home/user\n"
  "/home//user"
];
assert valid {
  users.users.second = {
    description = "Second login";
    homeDirectory = "/home/team/second";
    stateVersion = "26.05";
  };
};
assert valid {
  users.users.fixture.development = {
    neovimPath = "/home/fixture/src/neovim";
    hyprlandPath = "/home/fixture/src/hyprland";
  };
};
assert lib.all (name: !(builtins.elem name packages.pacman)) [
  "podman"
  "openrazer-daemon"
  "amd-ucode"
];
assert lib.all (module: !(valid module)) [
  { typo = true; }
  { deployment.username = lib.mkForce "missing"; }
  { users.users.fixture.admin = lib.mkForce false; }
  { users.users.fixture.description = 42; }
  { users.users.fixture.modules.unknown.enable = true; }
  { users.users.fixture.development.neovimPath = "relative/path"; }
  { users.users.fixture.development.hyprlandPath = 123; }
  { users.users.fixture.development.unknown = "invalid"; }
  {
    users.users.Bad = {
      description = "Invalid name";
      homeDirectory = "/home/bad";
      stateVersion = "26.05";
    };
  }
  { hardware.initramfs.images = [ "/boot/../etc/image" ]; }
  {
    users.users.second = {
      description = "Duplicate home";
      homeDirectory = "/home/fixture";
      stateVersion = "26.05";
    };
  }
  { networking.firewal.enable = true; }
  { services.fstrim.enable = "yes"; }
  { services.powerpanel.runtimeThreshold = -1; }
  { services.powerpanel.lowbattThreshold = 100; }
  { networking.hostname.name = "../bad"; }
  {
    networking.firewall.rules = [
      {
        protocol = "tcp";
        fromPort = 0;
      }
    ];
  }
  { users.users.fixture.profiles.unknown.enable = true; }
];
pkgs.runCommand "configuration-interface" { } ''
  test -x ${minimal.arch-switch}/bin/arch-switch
  test -x ${minimalRole.homes."fixture@fixture".activationPackage}/activate
  test -x ${freshInstall.deployment}/bin/box-workstation
  test -x ${freshInstall.homes."alice@box".activationPackage}/activate
  test -x ${minimal.homes."fixture@fixture".activationPackage}/activate
  test -x ${headlessHome.activationPackage}/activate
  test -x ${overriddenHome.activationPackage}/activate
  test -x ${home.activationPackage}/activate
  touch "$out"
''
