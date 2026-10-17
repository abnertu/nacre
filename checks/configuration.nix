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
    services.gitlabRunner.enable = false;
    services.personalAgent.enable = false;
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
    users.users.abnertu.modules.noctalia-config.enable = false;
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
        users.users.abnertu = {
          modules.hyprland.enable = false;
          modules.noctalia-storage.enable = false;
          homeModules = lib.mkForce [ ];
        };
      }
    )
  ];
  home = fixtures.home [ disabledModule ] "abnertu";
  overrideModule = (
    { lib, ... }:
    {
      networking.hostname.name = "overridden";
      time.timeZone = "UTC";
      networking.firewall.rules = lib.mkForce [ ];
      users.users.abnertu.home = {
        programs.git.enable = false;
        home.packages = [ pkgs.hello ];
      };
    }
  );
  override = evaluate [ overrideModule ];
  headlessHome = fixtures.home [ { desktop.enable = false; } ] "abnertu";
  overriddenHome = (fixtures.deploy [ overrideModule ]).homes."abnertu@overridden";
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
              "abnertu"
              "profiles"
              "workstation"
              "enable"
            ]
          ) { deployment.profile = "base"; }
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
  hotspot = evaluate [ { networking.hotspot.enable = true; } ];
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
assert hotspot.host.systemSettings.hotspot.channel == 36;
assert hotspotOverride.host.systemSettings.hotspot.channel == 149;
assert hotspotOff.host.systemSettings.hotspot == null;
assert hotspotParentOff.host.systemSettings.hotspot == null;
assert disabled.host.ai.llama.enable;
# Check the composed initialization, including Home Manager's own definitions.
assert lib.assertMsg (lib.hasInfix "powerlevel10k.zsh-theme" home.config.programs.zsh.initContent)
  "zsh initialization lost p10k";
assert lib.all (text: lib.hasInfix text home.config.programs.zsh.initContent) [
  ".p10k.zsh"
  "autosuggest-accept"
  "zsh-syntax-highlighting.zsh"
  "oh-my-zsh.sh"
  "fzf --zsh"
];
assert switchesWork;
assert builtins.length merged.host.systemSettings.firewall.rules == 2;
assert base.config.programs.ai.enable && base.config.virtualization.kvm.gui.enable;
assert base.host.systemSettings.trim.enable;
assert override.host.name == "overridden" && override.host.systemSettings.timeZone == "UTC";
assert override.host.systemSettings.firewall.rules == [ ];
assert disabled.host.runnerConfigFiles == [ ];
assert !disabled.host.personalAgent.enable;
assert !disabled.host.powerpanel.enable;
assert !(builtins.elem "powerpanel" packages.aur);
assert !overriddenHome.config.programs.git.enable;
assert lib.all
  (name: lib.any (package: (package.pname or "") == name) overriddenHome.config.home.packages)
  [
    "bat"
    "hello"
  ];
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
assert lib.all (homeDirectory: !(valid { users.users.abnertu = { inherit homeDirectory; }; })) [
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
  users.users.abnertu.development = {
    neovimPath = "/home/abnertu/src/neovim";
    hyprlandPath = "/home/abnertu/src/hyprland";
  };
};
assert lib.all (name: !(builtins.elem name packages.pacman)) [
  "podman"
  "openrazer-daemon"
  "amd-ucode"
];
assert (import ../modules/gitlab-runner { inherit lib pkgs; }).packages == { };
assert lib.all (module: !(valid module)) [
  { typo = true; }
  { deployment.username = lib.mkForce "missing"; }
  { users.users.abnertu.admin = lib.mkForce false; }
  { users.users.abnertu.description = 42; }
  { users.users.abnertu.modules.unknown.enable = true; }
  { users.users.abnertu.development.neovimPath = "relative/path"; }
  { users.users.abnertu.development.hyprlandPath = 123; }
  { users.users.abnertu.development.unknown = "invalid"; }
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
  { users.users.abnertu.profiles.unknown.enable = true; }
];
pkgs.runCommand "configuration-interface" { } ''
  test -x ${minimal.arch-switch}/bin/arch-switch
  test -x ${minimal.homes."abnertu@fixture".activationPackage}/activate
  test -x ${headlessHome.activationPackage}/activate
  test -x ${overriddenHome.activationPackage}/activate
  test -x ${home.activationPackage}/activate
  touch "$out"
''
