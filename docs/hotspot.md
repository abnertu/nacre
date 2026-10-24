# Wi-Fi hotspot

Nacre adopts an existing NetworkManager AP connection by unique name and manages its public properties. NetworkManager keeps the UUID, WPA credentials and other fields. The adapter does not read or print the password.

## Preparing the connection

Before you enable `networking.hotspot`, do these steps:

1. Start NetworkManager.
2. Create the named WPA-personal AP connection. Keep its password in the protected storage of NetworkManager.
3. Make sure that the declared wireless and uplink interfaces exist.
4. Make sure that no other connection holds the wireless interface.

Set `networking.hotspot.interface` and `.uplink` for the hardware. Otherwise, disable the feature. Missing interfaces, duplicate or non-AP connections, unsafe ownership and failed queries stop core preflight.

## Deploying and verifying

```bash
nacre switch
nmcli -f DEVICE,TYPE,STATE device status
sudo ufw status verbose
```

Changed AP properties can activate the connection again and briefly disconnect clients. An unchanged healthy AP keeps running. With firewall management, Nacre supplies IPv4 DHCP, gateway DNS and forwarding rules for the chosen subnet and uplink. NetworkManager supplies NAT. Other traffic stays default-deny.

Check address assignment, DNS and internet access from a client. `iw dev <interface> info` shows radio state.

## Recovery

Keep pending markers under `/var/lib/nix-config/arch/`. Fix the reported cause, then run again. When you disable management, the connection and credentials stay. After you change the subnet, interface or uplink, review stale manual rules. Deployment cannot find their owner.
