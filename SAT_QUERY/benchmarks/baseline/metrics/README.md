# Baseline Metrics

The current runner records:

- model warmup time;
- per-query cold/warm process latency;
- intent selected by the router;
- backend and model identifiers;
- returned confidence;
- warning list;
- region and label counts;
- structured failure category when a query fails.

Accuracy metrics are `not_evaluable` for the current fixture set because no ground truth is available. The absence of a metric is an explicit baseline result, not a zero score.
