# MFNavis GoTo and tracking correction

Verified against the working tree on 2026-10-10. The detailed state diagrams,
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
   Explicit user Tracking On can release the latch after the actual violation has cleared.

The 2026-10-10 control audit passed 881 tests. Hardware stopping latency and long-outage
correction accuracy remain field verification items. See [validation](validation_ko.md).
