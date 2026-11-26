# systemd.units and systemd.services: system units that the core adapter
# writes, enables, restarts and withdraws. A unit without content is a
# packaged unit that Nacre only enables and keeps running.
{ config, lib, ... }:
let
  inherit (lib) mkOption types;
  value = types.oneOf [
    types.bool
    types.int
    types.str
    (types.listOf types.str)
  ];
  common = {
    enable = mkOption {
      type = types.bool;
      default = true;
      description = "Whether Nacre manages this unit. A disabled unit is withdrawn like a removed one.";
    };
    wantedBy = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Targets that want an authored unit. Nacre enables and starts an authored unit only when this is set.";
    };
    overrideStrategy = mkOption {
      type = types.enum [
        "asfile"
        "asDropin"
      ];
      default = "asfile";
      description = ''
        `asfile` writes the whole unit. `asDropin` writes `<unit>.d/overrides.conf`
        over the packaged unit and never enables, starts or stops it.
      '';
    };
    restartTriggers = mkOption {
      type = types.listOf types.anything;
      default = [ ];
      description = "Values whose change restarts the running unit, such as the text of its configuration files.";
    };
    restartIfChanged = mkOption {
      type = types.bool;
      default = true;
      description = "Whether a change of an authored unit file restarts the running unit.";
    };
    adopt = mkOption {
      type = types.bool;
      default = false;
      description = "Replace an existing unit file that differs and that Nacre does not record; Nacre saves the original.";
    };
  };
  render =
    entries:
    lib.concatStrings (
      lib.mapAttrsToList (
        key: item:
        if builtins.isList item then
          lib.concatMapStrings (part: "${key}=${part}\n") item
        else if builtins.isBool item then
          "${key}=${lib.boolToString item}\n"
        else
          "${key}=${toString item}\n"
      ) entries
    );
  section = name: entries: lib.optionalString (entries != { }) "[${name}]\n${render entries}";
  serviceText =
    service:
    let
      dropin = service.overrideStrategy == "asDropin";
      unit =
        lib.optionalAttrs (service.description != null) { Description = service.description; }
        // lib.mapAttrs (_: lib.concatStringsSep " ") (
          lib.filterAttrs (_: list: list != [ ]) {
            After = service.after;
            Before = service.before;
            Wants = service.wants;
            Requires = service.requires;
          }
        )
        // service.unitConfig;
      environment = lib.optionalAttrs (service.environment != { }) {
        Environment = lib.mapAttrsToList (key: item: "\"${key}=${item}\"") service.environment;
      };
      install = lib.optionalAttrs (!dropin && service.wantedBy != [ ]) {
        WantedBy = lib.concatStringsSep " " service.wantedBy;
      };
    in
    lib.concatStringsSep "\n" (
      lib.filter (text: text != "") [
        (section "Unit" unit)
        (section "Service" (environment // service.serviceConfig))
        (section "Install" install)
      ]
    );
  authored =
    service:
    service.description != null
    || lib.any (list: list != [ ]) [
      service.after
      service.before
      service.wants
      service.requires
    ]
    || lib.any (attrs: attrs != { }) [
      service.environment
      service.unitConfig
      service.serviceConfig
    ];
in
{
  options.systemd = {
    units = mkOption {
      type = types.attrsOf (
        types.submodule {
          options = common // {
            text = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Unit file content. Without it, Nacre enables and starts the packaged unit.";
            };
          };
        }
      );
      default = { };
      description = "System units by full name, such as `demo.service` or `libvirtd.socket`.";
    };
    services = mkOption {
      type = types.attrsOf (
        types.submodule {
          options = common // {
            description = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "The unit description.";
            };
            after = mkOption {
              type = types.listOf types.str;
              default = [ ];
              description = "Units that this unit starts after.";
            };
            before = mkOption {
              type = types.listOf types.str;
              default = [ ];
              description = "Units that this unit starts before.";
            };
            wants = mkOption {
              type = types.listOf types.str;
              default = [ ];
              description = "Units that this unit wants.";
            };
            requires = mkOption {
              type = types.listOf types.str;
              default = [ ];
              description = "Units that this unit requires.";
            };
            environment = mkOption {
              type = types.attrsOf types.str;
              default = { };
              description = "Environment variables of the service. Never put secrets here.";
            };
            unitConfig = mkOption {
              type = types.attrsOf value;
              default = { };
              description = "More `[Unit]` keys. A list repeats its key.";
            };
            serviceConfig = mkOption {
              type = types.attrsOf value;
              default = { };
              description = "`[Service]` keys. A list repeats its key; an empty string resets it.";
            };
          };
        }
      );
      default = { };
      description = "System services by name without the `.service` suffix. They render into `systemd.units`.";
    };
  };

  config.systemd.units = lib.mapAttrs' (
    name: service:
    lib.nameValuePair "${name}.service" {
      # Scalars pass at default priority, so a direct systemd.units definition wins.
      enable = lib.mkDefault service.enable;
      overrideStrategy = lib.mkDefault service.overrideStrategy;
      restartIfChanged = lib.mkDefault service.restartIfChanged;
      adopt = lib.mkDefault service.adopt;
      inherit (service) wantedBy restartTriggers;
      text = lib.mkIf (authored service) (serviceText service);
    }
  ) config.systemd.services;
}
