# MF PiFinder GPS Aiding Plan (u-blox only)

> OS references below describe the dated design/migration baseline. Current
> MFNavis installation uses [Trixie 64-bit / Python 3.13](mf_trixie_install_en.md).

Created: 2026-07-14
Status: design draft (for review before implementation)

This document describes the design and operation flows for injecting the
Raspberry Pi's time, position, and assistance data into the u-blox receiver
(GEP-M1025, M10 SPG 5.10) **at the moment the user requests an injection**,
to mitigate the full cold start the receiver falls into after longer
power-off periods. The flows and policies here are to be agreed on before
any implementation.

## Background

- The GEP-M1025 backs up its RTC/BBR with a supercapacitor, not a battery.
  It holds for minutes to a few hours, so after a day powered off the
  receiver loses time, ephemeris, and almanac and starts fully cold every
  session. (Its configuration persists in flash.)
- Cold vs warm start: the C/N0 of an already-tracked satellite is the same,
  but **acquisition sensitivity and TTFF differ greatly**. A cold receiver
  must blind-search the full Doppler x code space for every satellite
  (acquisition threshold ~ -148 dBm on the M10); warm/hot searches a narrow
  window and operates near the reacquisition sensitivity (~ -160 dBm). The
  effective difference is 10-15 dB.
- The 2026-07-14 diagnosis confirmed PiFinder-body EMI costs the GPS about
  10-15 dB (A-B-A measurement). Aiding partially offsets that loss, which
  makes it a practical workaround as well.

## Goals

- Turn the receiver's start from cold into warm (close to hot where
  possible) **when the user requests an injection** (Inject Now on
  LCD/Web). **There is no automatic injection at boot** — the user always
  decides when the receiver is written to.
- **Fully offline operation.** No internet, no external service signup,
  no account of any kind.
- The user can enable/disable each method and trigger inject/save manually.
- Do not disturb the existing GPS flow (gpsd, gps_gpsd/gps_ubx, time sync
  helper).
- Failures must never block boot or GPS reception (best-effort).

## Scope and assumptions

- **u-blox only**: UBX-MGA/UPD is u-blox proprietary. Gate on **receiver
  detection**, not config — gpsd `DEVICES` reports `driver == "u-blox"`
  (this device: `SW ROM SPG 5.10, PROTVER=34.10`). Works with either
  PiFinder GPS backend as long as the receiver is u-blox.
- **Use packages**: sends go through gpsd's `ubxtool`. Bookworm ships
  `/usr/bin/ubxtool` but it needs the `python3-gps` package (add to
  `pifinder_setup.sh`). If gpsd runs with `-b` (readonly) the feature
  disables itself and records the reason in status.
- Receiving (ACK checks, DBD capture) reuses the repo's `UBXParser` gpsd
  raw watch (`?WATCH raw:2`). No new serial access is created — gpsd keeps
  owning the port.
- The ROM firmware (SPG 5.10) may not support `UBX-UPD-SOS` (flash
  save/restore), so it is out of scope; host-side storage (② MGA-DBD) is
  the single backup mechanism.

## The two methods

| # | Method | Data | Effect | Default |
| --- | --- | --- | --- | --- |
| ① | MGA-INI time+position | Pi clock (chrony/RTC), PiFinder location | cold → warm; shrinks the search space | On |
| ② | MGA-DBD backup/restore | nav DB the receiver actually collected (ephemeris/almanac) | near hot if recent, warm later | On |

- **Both methods are user-selectable.** ① is no exception — it has its
  own toggle (`gps_aiding_ini_enabled`). No method injects anything once
  the user turns it off.
- When ① is enabled it is always injected first (the receiver needs time
  to validate the data that follows).
- ② is stored and managed together with location metadata so the system
  can react immediately when the observing site changes (see "Reacting to
  location changes").
- Neither method needs the internet.

### Excluded method: AssistNow (MGA-ANO)

u-blox AssistNow orbit predictions (legacy Online/Offline, successor
Predictive Orbits) could use the same injection path, but they are
**excluded from this plan because they require an external service
signup**:

- Legacy Online/Offline hit EOM/EOS on 2026-05-31; new classic tokens are
  no longer issued.
- The successor, Predictive Orbits, is free for the M10 but requires a
  Thingstream account plus ZTP device registration (a chipcode credential
  derived from the receiver's `UBX-SEC-UNIQID`).

PiFinder's principle here is offline, account-free operation, so this is
not adopted. The research notes on the data format (UBX-MGA-ANO) and the
access procedure remain in git history (versions up to `fb86262`) for a
future revisit if ever needed.

## Architecture

```text
New module: python/PiFinder/gps_aiding.py
Data:       ~/PiFinder_data/gps_aiding/
              dbd/  snapshot_*.ubx   (② snapshots, rotated)
              dbd/  index.json       (snapshot meta: time, location, source)
Status:     ~/PiFinder_data/gps_aiding_status.json
```

Execution:

- **All injection is user-requested**: server.py routes and LCD callbacks
  call the module's inject functions directly. No new queue, and no
  boot-time injection path exists.
- **The background worker only does ② periodic DBD backups**: the GPS
  process starts a `gps_aiding.start_worker()` daemon thread, but this
  worker never injects aiding data — it only **reads and stores** DBD
  periodically while the fix is locked. It acts only after the gpsd
  connection is up and the receiver is detected as u-blox.
- **Serialization**: every receiver write takes a file lock
  (`gps_aiding.lock`, flock), safe across processes.
- Sends run `ubxtool -P 34.10 -c CLASS,ID,<hex payload>` as a subprocess;
  verification/capture uses the UBXParser raw watch. MGA ACKs only arrive
  when `CFG-NAVSPG-ACKAIDING` is enabled, so ACKs are "recorded when seen"
  and their absence is not treated as failure (fire-and-forget allowed).

## Injection request flow

Injection runs only when the user presses `Inject Now` on the LCD or Web.

```mermaid
flowchart TD
    A[user requests Inject Now<br/>LCD or Web] --> B{gpsd ready and driver == u-blox?}
    B -->|no| Z1[skip aiding - reason into status]
    B -->|yes| C{gps_aiding_enabled?}
    C -->|no| Z1
    C -->|yes| C2{ini_enabled?}
    C2 -->|no| J
    C2 -->|yes| D{time trustworthy?<br/>chrony synced or RTC valid}
    D -->|yes| E[inject MGA-INI-TIME_UTC<br/>honest tAcc]
    D -->|no| F[skip time]
    E --> G{position trustworthy?<br/>locked location or recent fix}
    F --> G
    G -->|yes| H[inject MGA-INI-POS_LLH<br/>posAcc from location error]
    G -->|no| I[skip position]
    H --> J{dbd_enabled and snapshot exists?}
    I --> J
    J -->|yes| K[select snapshot and restore DBD]
    J -->|no| P[done]
    K --> P
    P --> Q[write gps_aiding_status.json<br/>per-method result/time/ACK]
```

Injection order principle: **time → position → DBD**. The receiver needs
time first to judge the validity of the ephemeris data that follows.

## ② MGA-DBD save/restore flows

Save (backup):

```mermaid
flowchart TD
    A[save trigger] --> A1[periodic: every N min while fix locked<br/>default 15 min]
    A --> A2[manual: Web/LCD 'Save DBD']
    A --> A3[shutdown: PiFinder shutdown hook]
    A1 --> B{GPS fix locked?}
    A2 --> B
    A3 --> B
    B -->|no| Z[skip - DB has little value without lock]
    B -->|yes| C[open UBXParser raw watch]
    C --> D[send UBX-MGA-DBD poll]
    D --> E[collect DBD response frames<br/>all within timeout]
    E --> F[store snapshot_YYYYmmdd_HHMMSS.ubx]
    F --> G[update index.json:<br/>saved_at, lat, lon, source, msg count]
    G --> H[rotate old snapshots<br/>beyond max_snapshots]
```

Restore (at injection request):

```mermaid
flowchart TD
    A[DBD restore<br/>one step of the Inject Now flow] --> B{snapshots in index.json?}
    B -->|no| Z[skip]
    B -->|yes| C[determine intended location<br/>PiFinder selected location or last fix]
    C --> D{snapshot with age < 4h and<br/>distance < location_match_km?}
    D -->|yes| E[select it<br/>ephemeris still valid - near hot]
    D -->|no| F[select newest snapshot<br/>almanac value lasts weeks - warm]
    E --> G[inject the snapshot's DBD messages]
    F --> G
    G --> H[the following INI-POS step<br/>corrects position to the current value]
    H --> I[status: chosen snapshot,<br/>age, distance, msg count]
```

- Ephemeris is only valid ~4 hours, so "age < 4h at the same site" is the
  best case. Otherwise the newest snapshot is injected for its
  almanac/ionosphere value (always better than cold, never harmful).
- Location tagging lives in the snapshot metadata (index.json). Snapshots
  are not kept per-site — ephemeris/almanac are location independent, and
  position is ①'s job. The distance match only decides whether to trust a
  snapshot as hot-start grade.

## Reacting to location changes

```mermaid
flowchart TD
    A[user changes location<br/>locations pick / GPS lock / Web entry] --> B{aiding + ini + position<br/>all enabled and u-blox?}
    B -->|no| Z[do nothing]
    B -->|yes| C[re-inject MGA-INI-POS_LLH immediately<br/>new position + posAcc]
    C --> D[status: last_pos_inject]
```

- For users moving between observing sites, the receiver's search
  assumptions update the moment the location changes. Hook points: the
  main.py `gps_msg == "fix"` path when the source is not GPS (manual/saved
  location applied) and the locations callbacks.
- A location change is an explicit user action, so this stays within the
  "inject at user request" principle — it is not an unattended automatic
  injection like a boot hook would be.

## User control (UI)

LCD:

```text
Settings > Advanced > GPS Settings > GPS Aiding
  Aiding        Off / On          (gps_aiding_enabled)
  Use INI       Off / On          (gps_aiding_ini_enabled, ① time+position)
  Use DBD       Off / On          (gps_aiding_dbd_enabled)
  Inject Now    [action]          (re-inject all enabled methods)
  Save DBD      [action]          (back up DBD now)
```

Web (a GPS card or Tools section):

- Per-method toggles (including separate ① time/position toggles)
- Status: last inject time/result per method, DBD snapshot list (time,
  location, age)
- Buttons: `Inject Now`, `Save DBD Now`
- Detailed knobs (intervals, thresholds) are Web-only

## Config keys (default_config.json)

```text
gps_aiding_enabled            true    whole feature
gps_aiding_ini_enabled        true    ① (user-selectable toggle, LCD/Web)
gps_aiding_time               true    ① detail: time injection (Web only)
gps_aiding_position           true    ① detail: position injection (Web only)
gps_aiding_dbd_enabled        true    ②
gps_aiding_dbd_interval_min   15      periodic backup interval
gps_aiding_dbd_max_snapshots  5       rotation depth
gps_aiding_dbd_match_km       100     hot-start-grade distance threshold
```

All keys persist like normal settings (no session-only switch as in the
LiveCam processing case — aiding does not consume resources continuously).

## Safety rules

- **Never block the UI or GPS reception**: injection runs only on user
  request, every step has a timeout (sends a few seconds), and failures
  log + record status and move on. The LCD/Web stay responsive during an
  injection (background execution + status display).
- **Never inject false data**:
  - Time: only when chrony is synced or the time sync helper trusts its
    source. Set `tAccS/Ns` honestly (hundreds of ms to seconds for NTP,
    large for RTC).
  - Position: only a locked saved location or a recent GPS fix. Reflect
    the location error in `posAcc` with a floor. When unsure, skip — a
    wrong injected position is worse than none.
- All receiver writes serialize through flock across processes. If gpsd
  runs with `-b`, disable with a status notice.
- Missing/broken ubxtool (package not installed) disables the feature with
  a status notice.

## Message/tool reference

```text
Send: ubxtool -P 34.10 -c <class,id,payload>
  MGA-INI-TIME_UTC   0x13 0x40 (type=0x10)  time + tAcc
  MGA-INI-POS_LLH    0x13 0x40 (type=0x01)  lat/lon/alt + posAcc
  MGA-DBD            0x13 0x80              poll (empty) / restore (replay dump)
Receive: UBXParser raw watch
  MGA-ACK            0x13 0x60              only when ACKAIDING enabled
  MGA-DBD responses  0x13 0x80              capture target for backups
```

- UBXParser needs an MGA-class (0x13) raw frame passthrough (it currently
  parses NAV only). No parsing needed — store/replay the frame bytes as-is.

## Implementation stages

```text
Stage 1  gps_aiding.py skeleton + ① time/position + Inject Now entry
         point (Web) + status file (u-blox detection, flock, ubxtool
         wrapper, gating rules)
Stage 2  config keys + LCD menu + Web card/buttons (Inject Now)
Stage 3  ② DBD: UBXParser MGA passthrough, backup (periodic/manual/
         shutdown), restore, index.json, location tagging/selection
Stage 4  location-change hook, add python3-gps to pifinder_setup.sh,
         docs, field measurements
```

Each stage must be deployable and verifiable on its own. Stage 1 alone
already yields the cold → warm improvement.

## Test plan

- Indoors: send success/timeout, status file fields, flock contention,
  disabled behavior under gpsd `-b` / missing ubxtool.
- Outdoors A/B (reusing scripts/gps_acquisition_diag.py):
  - TTFF of cold (no injection) vs ① vs ①+②
    (each case measured from the user pressing Inject Now after boot)
  - hours powered off, then reboot, then Inject Now
  - moving between observing sites (location-change reaction)
- Regression: no impact on the existing GPS flow (fix/time/satellites
  messages, time sync helper). With aiding fully Off the behavior must be
  identical to today.

## Open questions (to settle before implementing)

1. Where the shutdown DBD backup hook lives — PiFinder's normal shutdown
   path is short; a systemd `ExecStop` script may be more reliable.
2. gpsd 3.22 ubxtool compatibility with the M10 (PROTVER 34) — the raw
   `-c` send should be fine, but verifying this on hardware is the first
   task of Stage 1.
