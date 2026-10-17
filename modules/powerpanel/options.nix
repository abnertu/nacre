{ lib }:
let
  inherit (lib) mkOption types;
  bounded = low: high: types.ints.between low high;
  option =
    type: default: description:
    mkOption { inherit type default description; };
in
{
  enable = lib.mkEnableOption "CyberPower PowerPanel UPS daemon management";
  powerfailDelay =
    option (bounded 0 3600) 60
      "Delay in seconds after power failure before executing script and shutdown.";
  powerfailActive = option types.bool true "Whether to run shell script when a power failure occurs.";
  powerfailCmdPath =
    option types.str "/etc/powerpanel/pwrstatd-powerfail.sh"
      "Path of shell script executed on power failure.";
  powerfailDuration =
    option (bounded 0 3600) 0
      "Execution time limit in seconds for power failure script.";
  powerfailShutdown =
    option types.bool false
      "Whether daemon shuts down the system on power failure. Defaults to false to base shutdown on remaining runtime.";
  lowbattThreshold =
    option (bounded 0 90) 35
      "Battery capacity percentage threshold for identifying a Battery Low event.";
  runtimeThreshold =
    option (bounded 0 3600) 300
      "Remaining runtime in seconds threshold for identifying a Battery Low event.";
  lowbattActive = option types.bool true "Whether to run shell script when Battery Low occurs.";
  lowbattCmdPath =
    option types.str "/etc/powerpanel/pwrstatd-lowbatt.sh"
      "Path of shell script executed on Battery Low.";
  lowbattDuration = option (bounded 0 60) 0 "Execution time limit in seconds for Battery Low script.";
  lowbattShutdown =
    option types.bool true
      "Whether daemon shuts down the system on Battery Low event.";
  enableAlarm = option types.bool true "Whether to turn UPS audible alarm on.";
  shutdownSustain =
    option (bounded 0 3600) 600
      "Time in seconds for system shutdown before UPS cuts power.";
  turnUpsOff =
    option types.bool true
      "Whether daemon turns UPS power off after system shutdown is initiated.";
  upsPollingRate = option (bounded 1 60) 3 "UPS polling interval in seconds.";
  upsRetryRate = option (bounded 1 300) 10 "Retry interval in seconds when UPS is not found.";
  prohibitClientAccess =
    option types.bool false
      "Whether to prohibit communication with client tools like pwrstat.";
  allowedDeviceNodes =
    option types.str ""
      "Restricted device node paths (semicolon-separated) for UPS communication.";
  hibernate = option types.bool false "Whether to hibernate instead of shutting down on power event.";
  cloudActive = option types.bool false "Whether to enable CyberPower cloud solution.";
  cloudAccount = option types.str "" "Account for cloud server login.";
  extraConfig = option types.lines "" "Extra raw configuration lines appended to pwrstatd.conf.";
}
