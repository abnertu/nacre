# systemd.units and the typed systemd.services, .timers, .sockets and .paths:
# system units that the core adapter writes, enables, restarts and withdraws.
# A unit without content is a packaged unit that Nacre only enables and keeps
# running.
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
  # Typed unit kinds: the option name, the unit suffix and the section that
  # `<kind>Config` fills.
  kinds = {
    services = {
      suffix = "service";
      section = "Service";
    };
    timers = {
      suffix = "timer";
      section = "Timer";
    };
    sockets = {
      suffix = "socket";
      section = "Socket";
    };
    paths = {
      suffix = "path";
      section = "Path";
    };
  };
  configName = kind: "${kinds.${kind}.suffix}Config";
  # The kind's own section: services also take `environment`.
  sectionEntries =
    kind: unit:
    lib.optionalAttrs (kind == "services" && unit.environment != { }) {
      Environment = lib.mapAttrsToList (key: item: "\"${key}=${item}\"") unit.environment;
    }
    // unit.${configName kind};
  unitText =
    kind: unit:
    let
      dropin = unit.overrideStrategy == "asDropin";
      unitEntries =
        lib.optionalAttrs (unit.description != null) { Description = unit.description; }
        // lib.mapAttrs (_: lib.concatStringsSep " ") (
          lib.filterAttrs (_: list: list != [ ]) {
            After = unit.after;
            Before = unit.before;
            Wants = unit.wants;
            Requires = unit.requires;
          }
        )
        // unit.unitConfig;
      install = lib.optionalAttrs (!dropin && unit.wantedBy != [ ]) {
        WantedBy = lib.concatStringsSep " " unit.wantedBy;
      };
    in
    lib.concatStringsSep "\n" (
      lib.filter (text: text != "") [
        (section "Unit" unitEntries)
        (section kinds.${kind}.section (sectionEntries kind unit))
        (section "Install" install)
      ]
    );
  # A typed unit with only `wantedBy` or other `common` fields renders no text:
  # it enables the packaged unit.
  authored =
    kind: unit:
    unit.description != null
    || lib.any (list: list != [ ]) [
      unit.after
      unit.before
      unit.wants
      unit.requires
    ]
    || unit.unitConfig != { }
    || sectionEntries kind unit != { };
  typedOptions =
    kind:
    common
    // {
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
      unitConfig = mkOption {
        type = types.attrsOf value;
        default = { };
        description = "More `[Unit]` keys. A list repeats its key.";
      };
      ${configName kind} = mkOption {
        type = types.attrsOf value;
        default = { };
        description = "`[${kinds.${kind}.section}]` keys. A list repeats its key; an empty string resets it.";
      };
    }
    // lib.optionalAttrs (kind == "services") {
      environment = mkOption {
        type = types.attrsOf types.str;
        default = { };
        description = "Environment variables of the service. Never put secrets here.";
      };
    };
  typed =
    kind:
    mkOption {
      type = types.attrsOf (types.submodule { options = typedOptions kind; });
      default = { };
      description = "System ${kinds.${kind}.suffix} units by name without the `.${kinds.${kind}.suffix}` suffix. They render into `systemd.units`.";
    };
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
  }
  // lib.mapAttrs (kind: _: typed kind) kinds;

  config.systemd.units = lib.mkMerge (
    lib.mapAttrsToList (
      kind: _:
      lib.mapAttrs' (
        name: unit:
        lib.nameValuePair "${name}.${kinds.${kind}.suffix}" {
          # Scalars pass at default priority, so a direct systemd.units definition wins.
          enable = lib.mkDefault unit.enable;
          overrideStrategy = lib.mkDefault unit.overrideStrategy;
          restartIfChanged = lib.mkDefault unit.restartIfChanged;
          adopt = lib.mkDefault unit.adopt;
          inherit (unit) wantedBy restartTriggers;
          text = lib.mkIf (authored kind unit) (unitText kind unit);
        }
      ) config.systemd.${kind}
    ) kinds
  );
}
