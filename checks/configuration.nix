# Configuration evaluation against the fixture: option types, assertions and
# the values that the deployment derives from them.
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
            "@runner@"
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
            ""
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
  overrideModule =
    { lib, ... }:
    {
      networking.hostname.name = "overridden";
      time.timeZone = "UTC";
      networking.firewall.rules = lib.mkForce [ ];
      users.users.fixture.home = {
        programs.git.enable = false;
        home.packages = [ pkgs.hello ];
      };
    };
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
          # Home configuration and the derived, internal arch tree are not switches.
          else if name == "home" || (path == [ ] && name == "arch") then
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
  # environment.etc: the failed assertion messages, and the manifest entries.
  etcFailed =
    module:
    map (check: check.message) (
      lib.filter (check: !check.assertion) (evaluate [ module ]).config.assertions
    );
  etcFile = text: builtins.toFile "etc-entry" text;
  etcText =
    modules: name:
    (lib.findFirst (entry: entry.name == name) null (evaluate modules).config.arch.etc).text;
  mainConf = "NetworkManager/conf.d/main.conf";
  # Forwarding keys and container modules belong to the features that need them.
  forwarding = [
    "net.bridge.bridge-nf-call-iptables"
    "net.ipv4.ip_forward"
    "net.ipv6.conf.all.forwarding"
  ];
  kernelOf =
    extra:
    let
      inherit (evaluate [ (disabledModule // extra) ]) host;
    in
    {
      keys = lib.filter (key: builtins.elem key forwarding) (builtins.attrNames host.sysctl);
      modules = host.kernelModules;
    };
  # A machine home module overrides the defaults of Nacre's home modules.
  homeWith = config: (fixtures.home [ { users.users.fixture.home = config; } ] "fixture").config;
  plainAndDefault =
    get: set: value:
    lib.all (wrap: get (homeWith (set (wrap value))) == value) [
      (x: x)
      lib.mkDefault
    ];
  demoService = {
    systemd.services.demo = {
      description = "Demo";
      after = [ "network.target" ];
      environment.A = "1";
      serviceConfig = {
        ExecStart = [
          ""
          "/usr/bin/true"
        ];
        NoNewPrivileges = true;
        TimeoutSec = 5;
      };
      wantedBy = [ "multi-user.target" ];
    };
  };
  demoTimers = {
    systemd.timers.demo = {
      description = "Demo timer";
      timerConfig.OnCalendar = "daily";
      wantedBy = [ "timers.target" ];
    };
    systemd.sockets.demo = {
      socketConfig = {
        ListenStream = [ "/run/demo.sock" ];
        SocketMode = "0600";
      };
      wantedBy = [ "sockets.target" ];
    };
    systemd.paths.demo = {
      after = [ "local-fs.target" ];
      pathConfig.PathChanged = "/etc/demo";
      wantedBy = [ "paths.target" ];
    };
  };
  # Direct text for a typed unit conflicts with its rendered text.
  directTextFails =
    unit:
    !(builtins.tryEval (
      builtins.deepSeq
        (evaluate [
          demoTimers
          { systemd.units.${unit}.text = "[Unit]\n"; }
        ]).config.systemd.units.${unit}.text
        true
    )).success;
  relativeMessage =
    name: "environment.etc.\"${name}\" must be a relative path without empty, . or .. components";
in
assert etcFailed { environment.etc."/abs".text = "x"; } == [ (relativeMessage "/abs") ];
assert etcFailed { environment.etc."a/../b".text = "x"; } == [ (relativeMessage "a/../b") ];
assert etcFailed { environment.etc."a//b".text = "x"; } == [ (relativeMessage "a//b") ];
assert
  etcFailed { environment.etc."passwd".text = "x"; } == [
    "environment.etc.\"passwd\" names a path that another Nacre owner writes"
  ];
assert
  etcFailed { environment.etc."ufw/user.rules".text = "x"; } == [
    "environment.etc.\"ufw/user.rules\" names a path that another Nacre owner writes"
  ];
assert
  etcFailed {
    environment.etc."a".text = "x";
    environment.etc."a/b".text = "y";
  } == [ "environment.etc.\"a\" is a directory of another entry" ];
assert
  etcFailed {
    environment.etc."both" = {
      text = "x";
      source = etcFile "y";
    };
  } == [ "environment.etc.\"both\" defines both text and source at the same priority" ];
assert
  etcFailed { environment.etc."empty".mode = "0600"; } == [
    "environment.etc.\"empty\" defines neither text, source nor target"
  ];
assert
  etcFailed {
    users.groups = {
      svc = { };
      Upper = { };
    };
    users.systemUsers = {
      svc.group = "svc";
      fixture.group = "svc";
      orphan.group = "missing";
      "this-name-is-far-too-long-for-sysusers".group = "svc";
    };
  } == [
    "users.groups.\"Upper\" must match [a-z_][a-z0-9_-]{0,30}"
    "users.systemUsers.\"fixture\" is also a login account in users.users"
    "users.systemUsers.\"orphan\".group missing is not declared in users.groups"
    "users.systemUsers.\"this-name-is-far-too-long-for-sysusers\" must match [a-z_][a-z0-9_-]{0,30}"
  ];
assert lib.all
  (
    account:
    !(builtins.tryEval (
      builtins.deepSeq
        (evaluate [
          {
            users.groups.svc = { };
            users.systemUsers.svc = account;
          }
        ]).config.arch.systemUsers
        true
    )).success
  )
  [
    {
      group = "svc";
      description = "50% load";
    }
    {
      group = "svc";
      home = "/a//b";
    }
    {
      group = "svc";
      home = "/a/..";
    }
    {
      group = "svc";
      home = "/a:b";
    }
  ];
assert etcText [ { environment.etc.${mainConf}.text = "plain\n"; } ] mainConf == "plain\n";
assert
  etcText [ { environment.etc.${mainConf}.text = lib.mkDefault "default\n"; } ] mainConf
  == "default\n";
assert
  etcFailed {
    environment.etc = {
      "relative".target = "usr/share/x";
      "store".target = "${builtins.storeDir}/x";
      "moded" = {
        target = "/x";
        mode = "0600";
      };
      "plain".source = "/home/user/key";
      "folder".source = ../lib;
      "sysctl.d/90-x.conf".source = etcFile "x";
      "sysctl.d".target = "/x";
    };
  } == [
    "environment.etc.\"folder\".source must be a Nix path to a regular file or a store path with its context"
    "environment.etc.\"moded\" is a symlink; it keeps the default mode and group"
    "environment.etc.\"plain\".source must be a Nix path to a regular file or a store path with its context"
    "environment.etc.\"relative\".target must be an absolute path outside ${builtins.storeDir}"
    "environment.etc.\"store\".target must be an absolute path outside ${builtins.storeDir}"
    "environment.etc.\"sysctl.d\" is a directory of another entry"
    "environment.etc.\"sysctl.d\" is at or under a path that an adapter reads as text; declare it with text"
    "environment.etc.\"sysctl.d/90-x.conf\" is at or under a path that an adapter reads as text; declare it with text"
  ];
assert
  !(builtins.tryEval (
    builtins.deepSeq (etcText [
      { environment.etc."sysctl.d/99-nix-config.conf".text = "x = 1\n"; }
    ] "sysctl.d/99-nix-config.conf") true
  )).success;
assert
  (evaluate [ demoService ]).config.systemd.units."demo.service".text == ''
    [Unit]
    After=network.target
    Description=Demo

    [Service]
    Environment="A=1"
    ExecStart=
    ExecStart=/usr/bin/true
    NoNewPrivileges=true
    TimeoutSec=5

    [Install]
    WantedBy=multi-user.target
  '';
assert
  lib.mapAttrs (name: _: (evaluate [ demoTimers ]).config.systemd.units.${name}.text) {
    "demo.timer" = null;
    "demo.socket" = null;
    "demo.path" = null;
  } == {
    "demo.timer" = ''
      [Unit]
      Description=Demo timer

      [Timer]
      OnCalendar=daily

      [Install]
      WantedBy=timers.target
    '';
    "demo.socket" = ''
      [Socket]
      ListenStream=/run/demo.sock
      SocketMode=0600

      [Install]
      WantedBy=sockets.target
    '';
    "demo.path" = ''
      [Unit]
      After=local-fs.target

      [Path]
      PathChanged=/etc/demo

      [Install]
      WantedBy=paths.target
    '';
  };
assert lib.all directTextFails [
  "demo.timer"
  "demo.socket"
  "demo.path"
];
assert
  etcFailed (demoService // { environment.etc."systemd/system/demo.service".text = "x"; })
  == [ "environment.etc.\"systemd/system/demo.service\" is the file of a systemd.units declaration" ];
assert
  !(builtins.tryEval (
    builtins.deepSeq
      (evaluate [
        demoService
        { systemd.units."demo.service".text = "[Service]\n"; }
      ]).config.systemd.units."demo.service".text
      true
  )).success;
assert
  kernelOf { } == {
    keys = [ ];
    modules = [ ];
  };
assert
  kernelOf { virtualization.enable = true; } == {
    keys = forwarding;
    modules = [
      "bridge"
      "br_netfilter"
      "veth"
    ];
  };
assert
  kernelOf {
    networking.networkmanager.enable = true;
    networking.hotspot.enable = true;
  } == {
    keys = [ "net.ipv4.ip_forward" ];
    modules = [ ];
  };
assert
  kernelOf { services.tailscale.enable = true; } == {
    keys = [ "net.ipv4.ip_forward" ];
    modules = [ ];
  };
assert
  !builtins.elem "yt-dlp" (evaluate [ { packages.exclude = [ "yt-dlp" ]; } ]).config.arch.pacman;
assert
  etcFailed { packages.exclude = [ "hyprland" ]; } == [
    "packages.exclude names hyprland, which desktop requires"
  ];
assert
  etcFailed { packages.exclude = [ "not-a-package" ]; } == [
    "packages.exclude names not-a-package, which no Nacre inventory offers as a default"
  ];
assert
  etcFailed {
    packages.exclude = [ "yt-dlp" ];
    packages.extra.pacman = [ "yt-dlp" ];
  } == [ "packages.exclude and packages.extra both name yt-dlp" ];
# profiles/base: a Git default.
assert plainAndDefault (c: c.programs.git.settings.init.defaultBranch) (v: {
  programs.git.settings.init.defaultBranch = v;
}) "trunk";
# modules/home/shell-files.nix: the Powerlevel10k file.
assert plainAndDefault (c: c.home.file.".p10k.zsh".source) (v: {
  home.file.".p10k.zsh".source = v;
}) ./fixtures/configuration.nix;
# modules/home/config-files.nix: a whole text, not a concatenation.
assert plainAndDefault (c: c.xdg.configFile."qt5ct/qt5ct.conf".text) (v: {
  xdg.configFile."qt5ct/qt5ct.conf".text = v;
}) "[Appearance]\n";
# modules/home/hyprland.nix: the configuration source; .zprofile keeps merging.
assert plainAndDefault (c: c.xdg.configFile."hypr".source) (v: {
  xdg.configFile."hypr".source = v;
}) ./fixtures;
assert
  let
    text =
      (homeWith { home.file.".zprofile".text = "export EDITOR=nvim\n"; }).home.file.".zprofile".text;
  in
  lib.hasInfix "uwsm start" text && lib.hasInfix "EDITOR=nvim" text;
# modules/home/neovim.nix: the configuration source.
assert plainAndDefault (c: c.xdg.configFile."nvim".source) (v: {
  xdg.configFile."nvim".source = v;
}) ./fixtures;
# profiles/dev: the password store.
assert plainAndDefault (c: c.programs.password-store.enable) (v: {
  programs.password-store.enable = v;
}) false;
# modules/home/fcitx5.nix: an input-method variable.
assert plainAndDefault (c: c.home.sessionVariables.QT_IM_MODULE) (v: {
  home.sessionVariables.QT_IM_MODULE = v;
}) "ibus";
# modules/home/graphical-session.nix: a service command.
# Home Manager stores ExecStart as a list.
assert plainAndDefault (c: lib.toList c.systemd.user.services.vesktop.Service.ExecStart) (v: {
  systemd.user.services.vesktop.Service.ExecStart = v;
}) [ "/usr/bin/true" ];
# profiles/workstation: packages keep merging.
assert
  let
    names = map (p: p.pname or p.name) (homeWith { home.packages = [ pkgs.hello ]; }).home.packages;
  in
  builtins.elem "cava" names && builtins.elem "hello" names;
assert
  etcFailed { systemd.services.llama-swap.serviceConfig.ExecStart = "/usr/bin/true"; } == [
    "systemd.units.\"llama-swap.service\" renders a path that another Nacre owner writes"
  ];
assert hotspotOverride.host.systemSettings.hotspot.channel == 149;
assert hotspotOff.host.systemSettings.hotspot == null;
assert hotspotParentOff.host.systemSettings.hotspot == null;
assert switchesWork;
assert minimalRole.deploymentName == "fixture-minimal";
assert !minimalRole.configuration.config.desktop.enable;
assert !(minimalRole.homes."fixture@fixture".config.home.file ? ".zprofile");
assert !roleBelowHost.config.desktop.enable;
assert builtins.length merged.host.systemSettings.firewall.rules == 2;
assert override.host.name == "overridden" && override.host.systemSettings.timeZone == "UTC";
assert override.host.systemSettings.firewall.rules == [ ];
assert !disabled.host.powerpanel.enable;
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
assert packages.lizardbyte == [ ];
assert lib.all (name: !(builtins.hasAttr name home.config.systemd.user.services)) [
  "vesktop"
  "vicinae"
  "tailscale-systray"
];
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
pkgs.linkFarm "configuration-fixtures" [
  {
    name = "minimal";
    path = minimal.deployment;
  }
  {
    name = "minimal-role-home";
    path = minimalRole.homes."fixture@fixture".activationPackage;
  }
  {
    name = "fresh-install";
    path = freshInstall.deployment;
  }
  {
    name = "headless-home";
    path = headlessHome.activationPackage;
  }
  {
    name = "overridden-home";
    path = overriddenHome.activationPackage;
  }
  {
    name = "disabled-features-home";
    path = home.activationPackage;
  }
]
