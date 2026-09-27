# MF PiFinder Wi-Fi AP+STA Mode

PiFinder has three Wi-Fi modes.

| Mode | Meaning |
| --- | --- |
| `Client` | `wlan0` connects to a saved Wi-Fi network as a STA. Use this for internet access and updates. |
| `AP` | `wlan0` becomes the `PiFinderAP` access point. Phones/tablets connect to `10.10.10.1`. |
| `AP+STA` | `wlan0` stays connected as a STA, while the virtual `uap0` interface serves `PiFinderAP`. |

## Behavior

`AP+STA` uses one Raspberry Pi Wi-Fi radio as both STA and AP. Because it is a single radio, the AP must use the same channel as the associated STA.

In `AP+STA` mode, PiFinder does the following:

- Keeps `wlan0` under the existing `wpa_supplicant` STA configuration.
- Creates the `uap0` virtual AP interface.
- Runs `dnsmasq` on `uap0` for DHCP addresses from `10.10.10.2` to `10.10.10.20`.
- Runs `hostapd` on `uap0` for the PiFinder AP.
- Watches the STA channel and restarts `hostapd` when the STA channel changes.

During startup PiFinder waits briefly for the STA channel before starting the AP. If the STA is not connected yet or the channel is still unknown, PiFinder starts with default channel `7`. Once the STA channel is known, PiFinder updates the AP channel to match it.

## Settings

Web UI:

```text
Network Setup > Wifi Mode > AP+STA
```

The same Network page also manages:

- AP network name.
- AP IP address. The default is `10.10.10.1`; clients receive DHCP addresses on the same `/24` network.
- AP security mode: open or WPA2 password.
- AP password, 8 to 63 characters when WPA2 is selected.
- Saved STA networks.
- Nearby Wi-Fi scan results when adding a new STA network.
- AP+STA internet sharing. This is off by default.
- STA band preference: Auto, Prefer 2.4 GHz, or Prefer 5 GHz.
- AP connected devices, combining live station state with DHCP leases.

Device UI:

```text
Settings > WiFi Mode > AP+STA Mode
```

A system restart is required after changing the mode.

## STA Network Import

On a fresh Raspberry Pi OS Trixie install, the Wi-Fi configured by Raspberry Pi Imager may be stored as a NetworkManager profile instead of `/etc/wpa_supplicant/wpa_supplicant.conf`.

PiFinder imports these OS-provisioned profiles during setup and post-update migration so they appear in the saved STA network list. The web UI also reads NetworkManager profiles directly when possible, so the initial OS Wi-Fi can be shown even before it is rewritten into `wpa_supplicant`.

When adding a new STA network from the web UI, PiFinder scans nearby Wi-Fi networks and lets the user select an SSID. Manual SSID entry is still available for hidden networks or scan failures.

The editable `/etc/wpa_supplicant/wpa_supplicant.conf` file is owned by the PiFinder service user with mode `600`, so PiFinder can update saved STA networks without making Wi-Fi passwords world-readable.

## AP Connected Devices

The Network page shows devices that are visible on the PiFinder AP. Entries marked `Connected` are currently associated with hostapd. Entries marked `Lease only` are DHCP lease records that are not currently visible as associated AP stations.

## AP Security

The AP security setting is shared by `AP` and `AP+STA` modes because both modes use `/etc/hostapd/hostapd.conf`.

Supported modes:

- `Open`: no AP password.
- `WPA2 Password`: writes `wpa=2`, `wpa_key_mgmt=WPA-PSK`, and `rsn_pairwise=CCMP` to hostapd.

Changing AP security or password requires a restart before clients reconnect with the new setting.

Changing the AP IP address also requires a restart. After the restart, connect to the new AP IP address instead of `10.10.10.1`. The `gw.wlan` DNS alias is updated to the selected AP IP.

## AP+STA Internet Sharing

AP+STA can optionally share the STA-side internet connection with clients connected to the PiFinder AP. This uses IPv4 forwarding and an `nft` masquerade table owned by PiFinder.

The option is off by default. Enable it only when needed because routing traffic through the Pi can add system load and may be slow, especially while PiFinder is capturing, solving, or serving the web UI.

PiFinder enables sharing only when AP+STA mode is active and the STA interface has a default route. If STA internet is unavailable, the NAT table is removed and normal PiFinder AP control remains available.

## STA Band Preference

When the same SSID is available on both 2.4 GHz and 5 GHz, the Network page can steer the STA connection by setting a band preference.

Options:

- `Auto`: do not restrict the STA scan frequencies.
- `Prefer 2.4 GHz`: limit STA scans to common 2.4 GHz channels.
- `Prefer 5 GHz`: limit STA scans to common 5 GHz channels.

This is useful in AP+STA mode because the AP must follow the STA channel. If AP clients such as OnStep only support 2.4 GHz, set the STA preference to `Prefer 2.4 GHz` and connect PiFinder to a 2.4 GHz-capable STA network.

The selected band must be available for the saved STA SSID. If the selected band is not available, STA connection can fail until the preference is returned to `Auto` or changed to the available band.

## Related Files

```text
switch-apsta.sh
scripts/pifinder_apsta.sh
scripts/import_initial_wifi_networks.py
/etc/pifinder_apsta_nat.conf
pi_config_files/dhcpcd.conf.apsta
pi_config_files/pifinder_apsta_prepare.service
pi_config_files/pifinder_apsta_monitor.service
```

## Pi 4 / Pi 5 Compatibility

Both Pi 4 and Pi 5 use `wlan0` as the default Wi-Fi interface. AP+STA adds `uap0` on top of `wlan0`, so it is independent of the GPS UART board profile.

Pi 5 uses the same `wlan0`/`uap0` layout. If the STA connects on a 5 GHz channel, the AP may also restart on that 5 GHz channel, so the phone/tablet used for control must support that channel.
