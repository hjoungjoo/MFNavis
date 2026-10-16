# MFNavis GoTo and tracking correction

Updated against the working tree on 2026-10-17. The detailed state diagrams,
thresholds and validation are maintained in [the consolidated control design](mount_control_ko.md).

1. `off` refuses GoTo; `indi_mount` uses native GoTo; `mfnavis` uses the optical state machine.
2. Initial acceptance without an eligible anchor waits at most 12 seconds.
   An accepted GoTo waits indefinitely for a usable solve when optical arrival is still unknown.
3. Sync+GoTo requires fresh acknowledgements for SYNC mode, requested coordinates and SLEW mode.
   Arrival requires a valid exposure after the mount has actually stopped.
4. Before arrival, solve loss retains native tracking. Manual motion ends at the released field.
   LCD Align or SkySafari Align confirms user arrival without inventing a solve.
   The first eligible recovered solve fixes the actual tracking target once.
5. After optical arrival, enabled Tracking Guide retains native tracking and executes remaining
   correction using the last measured residual and confirmed drift, less estimated pulse travel.
   It does not repeatedly add the same stale error or feed predictions back into the PID.
6. A new solve replaces the estimated error and resumes normal optical correction/recovery.
   Solve loss alone does not cancel the target; explicit user actions and independent operating
   conditions such as parking, disconnection or driver rejection still apply.
7. A mount limit violation takes priority in every phase: invalidate queued motion, abort axes,
   switch tracking off and display the cause. Closing the dialog or recovering a solve cannot restart motion.
   Explicit user Tracking On or a new GoTo can release the latch after the actual violation has cleared.
   A new GoTo requires fresh stopped telemetry and safe current/sync and target coordinates;
   MFNavis still verifies the Sync acknowledgement before enabling tracking or slewing.
   The service waits for the matching limit acknowledgement, then resumes normal tracking and
   fine correction after arrival. Automatic correction cannot clear a limit latch.
8. A new MFNavis GoTo uses bounded manual-axis movements for the near approach
   (configured near range, capped at 60 arcmin), instead of repeating small GoTos.
   Select 4x/8x/20x/48x from each fresh axis residual: use the fastest rate whose
   planned 60%-residual travel lasts at least 0.6 seconds (4x near the target).
   The approximate thresholds are 2.01, 5.01 and 12.03 arcmin for 8x, 20x and 48x.
   Confirm the temporary speed before each movement, move one axis for at
   most 1.2 seconds, stop, and restore the user's original manual speed.
   User takeover, cancellation and a new GoTo stop this approach and restore speed first.
   After stopping, wait at least 0.5 seconds and require a new solve and idle mount.
   Pulse handoff is well inside the pulse capacity: 1.5 times final accuracy
   (1.5 arcmin with the default 1 arcmin accuracy; bounded to 0.75–15 arcmin).
   Final pulse guiding and arrival accuracy retain their existing policies.
9. After arrival, failed pulses within the recovery GoTo threshold no longer leave
   correction disabled until the target drifts farther away. A fresh post-pulse solve
   starts a bounded manual approach followed by pulses, without another native GoTo.
   A fresh post-motion arrival restores normal optical correction and solve holdover.
   Failed recovery retries wait 10 seconds and require fresh observations; after three
   failed attempts, report failure and require a new GoTo (or verified optical arrival).
   Native tracking remains on. User actions, limits, parking and tracking-off take priority.
   `recovering_manual`, `recovery_wait` and `failed` distinguish this from brief `settling`.

Delayed-solve/motor-response simulations are not hardware validation.

The 2026-10-10 control audit passed 881 tests. Hardware stopping latency and long-outage
correction accuracy remain field verification items. See [validation](validation_ko.md).
