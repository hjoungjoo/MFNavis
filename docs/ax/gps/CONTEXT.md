# GPS (MF fork)

The GPS process supplies position, time, satellite counts and communication
events to main through `gps_queue`. The last category is diagnostic only.

- **Fix**: a position that passes the backend's existing accuracy checks.
- **Time**: receiver time, governed by MF's separate validity and time-sync
  rules. Communication events never lock position or set system time.
- **Satellites**: MF retains four values: seen (signal-locked), used (in fix),
  in view, top C/N0 values.
  NAV-SAT remains preferred while fresh, with NAV-SVINFO fallback and
  NAV-PVT used-count handling unchanged.
- **Event**: any decoded UBX message or an undecodable-frame marker.
  GPSD publishes `TPV`/`SKY`; the fake backend publishes `FAKE`.
- **Marker**: `?XXYY` for an unsupported UBX class/id, `?CKSUM` for a checksum
  failure, `?NMEA` for checksum-valid navigation NMEA without a valid UBX
  frame in the same read batch. These indicate incoming frames, not a valid
  fix or time. NMEA is not decoded into navigation data by the UBX backend.
- **Comms row**: `GPS MSG` on STATUS shows the last reported event and its age;
  `NAV-` is omitted for space. Before any event it reads `--`.

`CommsPublisher` caps reporting at 20 Hz without throttling parsing or normal
fix/time/satellite messages. Main timestamps receipt using `time.monotonic()`;
STATUS uses the same clock so GPS-driven wall-clock changes cannot invert
the displayed age. This is age since receipt by main, not a precise serial
arrival timestamp. During bursts, events suppressed by the rate cap are not
displayed individually.

See [ADR 0032](../../adr/0032-ubx-parser-yields-undecodable-frames.md).

## Manual version query and stalled-navigation recovery

With `gps_type=ublox`, the GPS screen's long-square marking menu has a bottom
`Get VER` action. A dedicated `gps_command` queue delivers `get_version` to the
GPS process; the existing `gps` queue still carries readings to main. A manual
query shows firmware/protocol versions, or a device/response/send failure.
Repeated requests while a query is pending share that query. Fake and generic
backends do not receive hardware commands.

After 60 monotonic seconds without a decoded NAV message, the live UBX parser
attempts one MON-VER query. This covers startup, silence, NMEA-only streams,
noise and checksum failures. A one-second read timeout keeps the watchdog and
manual command handling alive on a silent connection. No position fix is
required: NAV messages without a satellite lock still count as normal traffic.

Before each query, refresh gpsd's `DEVICES` report. Only one local `/dev/`
receiver with driver `NMEA0183` or `u-blox`, not marked read-only, is eligible.
Send `b5620a0400000e34` through gpsd `?DEVICE` with its explicit device path.
Discovery and response waits are each limited to five seconds; drain waits to
two seconds. An unavailable/ambiguous device or failed send consumes the
automatic attempt for that outage. Only decoded NAV traffic rearms it; MON-VER,
ACKs, NMEA and reconnecting do not. Manual queries remain available afterward.
Restarting the GPS process starts a new watchdog interval.

File replay never sends queries. No receiver reset, baud change, aiding or
persistent configuration command is sent. gpsd may change the receiver's
active output configuration when it identifies it. Query attempts, versions,
failures and navigation recovery are logged at WARNING. Navigation resuming
is distinct from obtaining a position fix.

Historical NMEA-only recovery (superseded by the watchdog above on 2026-09-16):
[2026-09-09 report (English)](../../mf_report/mf_gps_ubx_recovery_20260909_en.md)
and [Korean](../../mf_report/mf_gps_ubx_recovery_20260909_ko.md).
