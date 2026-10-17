{
  lib,
  pkgs,
  config,
}:
let
  boolStr = b: if b then "yes" else "no";
  content = ''
    #
    # pwrstatd configuration file
    # Managed by nix-config.
    #

    # You must restart pwrstatd after changing this file in order for changes to take effect.
    # Ex:/etc/powerpanel/init.d/pwrstatd restart

    #
    # Action setting for event of Power Failure
    #

    # A delay time in seconds since event of Power Failure occur then to run shell
    # script and shutdown system. Allowed range is 0 ~ 3600. Default is 60 sec.
    powerfail-delay = ${toString config.powerfailDelay}

    # Enable to run shell script when the event of Power Failure occur.
    # The allowed options are yes and no. Default is yes.
    powerfail-active = ${boolStr config.powerfailActive}

    # Assign a path of script file for event of Power Failure.
    # The default is /etc/powerpanel/pwrstatd-powerfail.sh
    powerfail-cmd-path = ${config.powerfailCmdPath}

    # How much time in seconds to take script running for event of Power Failure.
    # The allowed range is 0 ~ 3600. Default is 0 sec.
    powerfail-duration = ${toString config.powerfailDuration}

    # Allow Daemon to shutdown system for event of Power Failure.
    # The allowed options are yes and no. Default is yes.
    powerfail-shutdown = ${boolStr config.powerfailShutdown}

    #
    # Action setting for event of Battery Low
    #

    # A threshold of Battery Capacity, If the battery capacity is lower than this
    # value and a event of Battery Low will be identified. The unit is percentage.
    # The allowed range is 0 ~ 90. Default is 35 %.
    lowbatt-threshold = ${toString config.lowbattThreshold}

    # A threshold of Remaining Runtime, If the Remaining Runtime is lower than this
    # value and a event of Battery Low will be identified. The unit is second.
    # The allowed range is 0 ~ 3600. Default is 300 sec.
    # Note: When meet this condition the below 'shutdown-sustain' property
    # will be ignored.
    runtime-threshold = ${toString config.runtimeThreshold}

    # Enable to run shell script when the event of Battery Low occur.
    # The allowed options are yes and no. Default is yes.
    lowbatt-active = ${boolStr config.lowbattActive}

    # Assign a path of script file for event of Battery Low.
    # The default is /etc/powerpanel/pwrstatd-lowbatt.sh
    lowbatt-cmd-path = ${config.lowbattCmdPath}

    # How much time in seconds to take script running for event of Battery Low.
    # The allowed range is 0 ~ 60. Default is 0 sec.
    lowbatt-duration = ${toString config.lowbattDuration}

    # Allow Daemon to shutdown system for event of Battery Low.
    # The allowed options are yes and no. Default is yes.
    lowbatt-shutdown = ${boolStr config.lowbattShutdown}

    # Turn UPS alarm on or off.
    # The allowed options are yes and no. Default is yes.
    enable-alarm = ${boolStr config.enableAlarm}

    # The necessary time in seconds for system shutdown.
    # The UPS will turn power off when this time is expired.
    # The allowed range is 0 ~ 3600. Default is 600 sec.(10 min.)
    # If the computer shutdown is cause by low runtime condition, the UPS will
    # turn power off when the time is expired that time is assigned on
    # 'runtime-threshold' property and it is no longer to refer the
    # 'shutdown-sustain' property.

    shutdown-sustain = ${toString config.shutdownSustain}

    # Daemon will turn UPS power off once it ask system shutdown cause by a power
    # event. Allowed options are yes and no. Default is yes.
    turn-ups-off = ${boolStr config.turnUpsOff}

    # The period of polling UPS in seconds.
    # The allowed range is 1 ~ 60. Default is 3 sec.
    ups-polling-rate = ${toString config.upsPollingRate}

    # the period of re-try to find available UPS in seconds since find nothing at
    # last time. The allowed range is 1 ~ 300. Default is 10 sec.
    ups-retry-rate = ${toString config.upsRetryRate}

    # Prohibiting daemon to provide communication mechanism for client, such as
    # pwrstat command. normally, it should be 'no'. It can be 'yes' if any security
    # consideration. Allowed options are yes and no. Default is no.
    prohibit-client-access = ${boolStr config.prohibitClientAccess}

    # The pwrstatd accepts four types of device node which includes the 'ttyS',
    # 'ttyUSB', 'hiddev', and 'libusb' for communication with UPS. The pwrstatd
    # defaults to enumerate all acceptable device nodes and pick up to use an
    # available device node automatically. But this may cause a disturbance to the
    # device node which is occupied by other software. Therefore, you can restrict
    # this enumerate behave by using allowed-device-nodes option. You can assign
    # the single device node path or multiple device node paths divided by a
    # semicolon at this option. All groups of 'ttyS', 'ttyUSB', 'hiddev', or
    # 'libusb' device node are enumerated without a suffix number assignment.
    # Note, the 'libusb' does not support suffix number only.
    allowed-device-nodes = ${config.allowedDeviceNodes}

    # Daemon will hibernate system to instead of system shutdown when power
    # event occur. Allowed options are yes and no. Default is no.
    hibernate = ${boolStr config.hibernate}

    # Enable cloud solution.
    # The allowed options are yes and no. Default is no.
    cloud-active = ${boolStr config.cloudActive}

    # Account for cloud server login.
    cloud-account = ${config.cloudAccount}
    ${lib.optionalString (config.extraConfig != "") "\n${config.extraConfig}"}
  '';
in
{
  inherit content;
  configFile = pkgs.writeText "pwrstatd.conf" content;
  enable = config.enable;
}
