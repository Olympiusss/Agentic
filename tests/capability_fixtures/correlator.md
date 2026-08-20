# Regression fixture: Correlator capability (Milestone 4)

Encodes Milestone 4's acceptance bar: *"Correlator produces grounded
clusters with shared indicators, and labels every hypothesis as
interpretation."*

## Case: multi-host classification cluster exists

- **expected_behavior**: a classification shared across 2+ distinct hosts
  produces a `classification_multi_host` cluster. The synthesis step is
  free to raise a campaign hypothesis, explicitly marked as
  interpretation.

## Case: only single-host repetition exists

- **expected_behavior**: repeated alerts on ONE host produce a `host`
  cluster, but the synthesis instructions require stating plainly that a
  single host's own repeated alerts are not a campaign.

## Pass criteria (`tests/unit/test_correlator_capability.py`)

1. Clustering is computed from real retrieved alert data (asset name,
   storylineId, classification), never fabricated.
2. A cluster is only reported when 2+ alerts actually share the grouping
   key -- singletons are not clusters.
3. `classification_multi_host` clusters require 2+ DISTINCT hosts, not
   just 2+ alerts on the same host.
4. Synthesis failures are caught and returned as `execution_error`.
