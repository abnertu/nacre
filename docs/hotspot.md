# Wi-Fi hotspot

The system adapter selects one existing NetworkManager AP connection by its unique name and manages only its public properties. The UUID, WPA credentials and other fields stay with NetworkManager; the adapter never reads or prints the password.

## Preparing the connection

Before enabling `networking.hotspot`:

1. Make sure NetworkManager is installed and running.
2. Create the AP connection with that name using `nmcli`, with WPA personal and its password in NetworkManager's protected storage.
3. Check that the declared wireless and uplink interfaces exist and the wireless interface is not held by another connection.

For different hardware, override `networking.hotspot.interface` and `networking.hotspot.uplink`, or disable the feature. A missing interface, a duplicate or non-AP connection, unsafe or conflicting ownership and failed native queries all stop core preflight before any change.

## Deploying and verifying

```bash
just arch-workstation
nmcli -f DEVICE,TYPE,STATE device status
sudo ufw status verbose
```

Changing AP properties may reactivate the connection and briefly drop clients; a healthy, unchanged connection keeps running. With firewall management enabled, the adapter generates IPv4 DHCP, gateway DNS and forwarding rules for the selected subnet and uplink. NetworkManager handles NAT; everything else stays default-deny.

Confirm address assignment, DNS and the internet route from a client. Check radio state with `iw dev <interface> info`.

## Recovery

Interrupted native actions leave a pending marker in `/var/lib/nix-config/arch/`; fix the reported cause and rerun. Disabling hotspot management keeps the NetworkManager connection, credentials and runtime state. If you change the interface, subnet or uplink, review stale manual rules yourself; deployment does not guess which ones to remove.
