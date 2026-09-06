# Entry timing: keep recommendation-only shadow analysis

Decision: defer execution gating during infrastructure cleanup. Existing timing
analysis remains an advisory/shadow feature. No new veto changes Scion or Omaha
entries, allocations, or exits in this batch.

Purpose: help compare an entry's technical context using timestamped price, volume,
volatility, moving averages, and earnings proximity. Existing assess outputs remain
the interface; reserve no speculative new score or trigger.

Before promoting timing to an actionable gate, specify its exact timestamp and
data-availability rules, thresholds, handling of unavailable data, and the order
of fill/decision events. Validate on historical replay with all inputs restricted
to information available at the simulated decision time. Compare against the same
strategy without the gate and report costs and failed/missing-data cases.

This decision does not block packaging, validation, persistence, or shared plumbing.
