# Wi-Fi hotspot

Nacre adopts a NetworkManager AP connection by unique name and manages its public properties. `nacre hotspot prepare` creates that connection. NetworkManager retains the UUID, WPA credentials and other fields. The adapter does not read or print the password.

## Preparing the connection

Before you deploy with `networking.hotspot`, do these steps:

1. Start NetworkManager. On a new host, deploy once without `networking.hotspot`.
2. Declare `networking.hotspot`.
3. Run `nacre hotspot prepare`. Type the password twice.
4. Make sure that the declared wireless and uplink interfaces exist.
5. Make sure that no other connection holds the wireless interface.

```bash
nacre hotspot prepare
nacre switch
```

Prepare creates a WPA2 (RSN, CCMP) AP with the declared properties and `autoconnect` off. It writes the password only into a root-only keyfile under `/etc/NetworkManager/system-connections/`. A password has 8 to 63 printable ASCII characters, or 64 hex digits. Prepare stops and writes nothing when the connection or its keyfile exists. When NetworkManager does not load the keyfile, prepare removes it again. You can also create the connection by hand.

The deployment applies the declared `autoconnect`. With `autoconnect = true`, it starts the AP. With `autoconnect = false`, run `nmcli connection up <connection>`.

Set `networking.hotspot.interface` and `.uplink` for the hardware. Otherwise, disable the feature. Missing interfaces, duplicate or non-AP connections, unsafe ownership and failed queries stop the system preflight.

## Deploying and verifying

```bash
nacre switch
nmcli -f DEVICE,TYPE,STATE device status
sudo ufw status verbose
```

Changed AP properties can activate the connection again and briefly disconnect clients. An unchanged healthy AP keeps running. With firewall management, Nacre supplies IPv4 DHCP, gateway DNS and forwarding rules for the chosen subnet and uplink. NetworkManager supplies NAT. Other traffic stays default-deny.

Check address assignment, DNS and internet access from a client. `iw dev <interface> info` shows radio state.

## Recovery

Keep pending markers under `/var/lib/nix-config/arch/`. Fix the reported cause, then run again. When the hotspot goes away, the connection gets its properties before Nacre back, and an AP that Nacre brought up goes down. The connection and credentials stay. After you change the subnet, interface or uplink, review stale manual rules. Deployment cannot determine who owns those rules.
