{ lib }:
let
  inherit (lib) mkOption types;
  bounded = low: high: types.ints.between low high;
in
{
  enable = lib.mkEnableOption "CyberPower PowerPanel UPS daemon management";
  powerfailDelay = mkOption {
    type = bounded 0 3600;
    default = 60;
    description = "Delay in seconds after power failure before executing script and shutdown.";
  };
  powerfailActive = mkOption {
    type = types.bool;
    default = true;
    description = "Whether to run shell script when a power failure occurs.";
  };
  powerfailCmdPath = mkOption {
    type = types.str;
    default = "/etc/powerpanel/pwrstatd-powerfail.sh";
    description = "Path of shell script executed on power failure.";
  };
  powerfailDuration = mkOption {
    type = bounded 0 3600;
    default = 0;
    description = "Execution time limit in seconds for power failure script.";
  };
  powerfailShutdown = mkOption {
    type = types.bool;
    default = false;
    description = "Whether daemon shuts down the system on power failure. Defaults to false to base shutdown on remaining runtime.";
  };
  lowbattThreshold = mkOption {
    type = bounded 0 90;
    default = 35;
    description = "Battery capacity percentage threshold for identifying a Battery Low event.";
  };
  runtimeThreshold = mkOption {
    type = bounded 0 3600;
    default = 300;
    description = "Remaining runtime in seconds threshold for identifying a Battery Low event.";
  };
  lowbattActive = mkOption {
    type = types.bool;
    default = true;
    description = "Whether to run shell script when Battery Low occurs.";
  };
  lowbattCmdPath = mkOption {
    type = types.str;
    default = "/etc/powerpanel/pwrstatd-lowbatt.sh";
    description = "Path of shell script executed on Battery Low.";
  };
  lowbattDuration = mkOption {
    type = bounded 0 60;
    default = 0;
    description = "Execution time limit in seconds for Battery Low script.";
  };
  lowbattShutdown = mkOption {
    type = types.bool;
    default = true;
    description = "Whether daemon shuts down the system on Battery Low event.";
  };
  enableAlarm = mkOption {
    type = types.bool;
    default = true;
    description = "Whether to turn UPS audible alarm on.";
  };
  shutdownSustain = mkOption {
    type = bounded 0 3600;
    default = 600;
    description = "Time in seconds for system shutdown before UPS cuts power.";
  };
  turnUpsOff = mkOption {
    type = types.bool;
    default = true;
    description = "Whether daemon turns UPS power off after system shutdown is initiated.";
  };
  upsPollingRate = mkOption {
    type = bounded 1 60;
    default = 3;
    description = "UPS polling interval in seconds.";
  };
  upsRetryRate = mkOption {
    type = bounded 1 300;
    default = 10;
    description = "Retry interval in seconds when UPS is not found.";
  };
  prohibitClientAccess = mkOption {
    type = types.bool;
    default = false;
    description = "Whether to prohibit communication with client tools like pwrstat.";
  };
  allowedDeviceNodes = mkOption {
    type = types.str;
    default = "";
    description = "Restricted device node paths (semicolon-separated) for UPS communication.";
  };
  hibernate = mkOption {
    type = types.bool;
    default = false;
    description = "Whether to hibernate instead of shutting down on power event.";
  };
  cloudActive = mkOption {
    type = types.bool;
    default = false;
    description = "Whether to enable CyberPower cloud solution.";
  };
  cloudAccount = mkOption {
    type = types.str;
    default = "";
    description = "Account for cloud server login.";
  };
  extraConfig = mkOption {
    type = types.lines;
    default = "";
    description = "Extra raw configuration lines appended to pwrstatd.conf.";
  };
}
