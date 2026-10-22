# Wi-Fi hotspot

Nacre adopts an existing NetworkManager AP connection by unique name and manages its public properties. NetworkManager retains the UUID, WPA credentials and other fields; the adapter does not read or print the password.

## Preparing the connection

Before enabling `networking.hotspot`, start NetworkManager and create the named WPA-personal AP connection with its password in NetworkManager's protected storage. Confirm that the declared wireless and uplink interfaces exist and that another connection does not hold the wireless interface.

Set `networking.hotspot.interface` and `.uplink` for the hardware, or disable the feature. Missing interfaces, duplicate or non-AP connections, unsafe ownership and failed queries stop core preflight.

## Deploying and verifying

```bash
nacre switch
nmcli -f DEVICE,TYPE,STATE device status
sudo ufw status verbose
```

Changed AP properties may reactivate the connection and briefly disconnect clients. An unchanged healthy AP keeps running. With firewall management enabled, Nacre supplies IPv4 DHCP, gateway DNS and forwarding rules for the chosen subnet and uplink; NetworkManager supplies NAT. Other traffic remains default-deny.

Check address assignment, DNS and internet access from a client. `iw dev <interface> info` shows radio state.

## Recovery

Keep pending markers under `/var/lib/nix-config/arch/`, fix the reported cause and rerun. Disabling management preserves the connection and credentials. Review stale manual rules after changing subnet, interface or uplink; deployment cannot infer their ownership.
