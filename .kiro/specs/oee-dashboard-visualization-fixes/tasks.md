# OEE Dashboard Visualization Fixes — Tasks

## Implementation Tasks

- [x] 1. Fix Y-axis label overlap in OEE TREND chart (App.jsx)
  - [x] 1.1 In the OEE TREND `LineChart` block, change `YAxis` `width={44}` to `width={60}`
  - [x] 1.2 In the OEE TREND `LineChart` block, change `margin={{ top: 10, right: 60, bottom: 30, left: 10 }}` to `margin={{ top: 10, right: 60, bottom: 30, left: 20 }}`

- [x] 2. Fix Y-axis label overlap in SPC Control Chart (App.jsx)
  - [x] 2.1 In the `SpcChart` component `LineChart`, change `YAxis` `width={44}` to `width={60}`
  - [x] 2.2 In the `SpcChart` component `LineChart`, change `margin={{ top: 10, right: 60, bottom: 30, left: 10 }}` to `margin={{ top: 10, right: 60, bottom: 30, left: 20 }}`

- [x] 3. Fix sudden OEE value jumps by merging WebSocket data (useOeeWebSocket.js)
  - [x] 3.1 Replace `setOeeData(msg.data)` with a functional state update that builds a `Map` keyed on `${machine_id}|${window_start}|${window_end}`, merges incoming windows over existing ones, and returns `Array.from(map.values())`

- [x] 4. Fix false ANOMALY alerts by using pre-batch SPC stats (spark_oee_stream.py)
  - [x] 4.1 Update `_detect_anomalies` function signature to accept `batch_ts` as a fourth parameter
  - [x] 4.2 In `_detect_anomalies`, add `AND calculated_at < %s` to the SPC fetch query and pass `batch_ts` as the second query parameter
  - [x] 4.3 Update the `_detect_anomalies` call in `write_batch` to pass `batch_ts` as the fourth argument

- [ ] 5. Write and run tests
  - [ ] 5.1 Write unit tests for the `useOeeWebSocket` merge logic: overlapping window update, new window append, multiple machines, empty initial state
  - [ ] 5.2 Write unit tests for `_detect_anomalies`: assert pre-batch SPC filter excludes current-batch row, assert no alert when no pre-batch row exists, assert genuine anomaly still fires
  - [ ] 5.3 Write property-based tests for the merge logic: for any random `(prevState, incomingMsg)` pair, assert no window key is lost and all incoming values are reflected
  - [ ] 5.4 Write property-based tests for anomaly detection: for random `(avg_oee, mean, std)` where `avg_oee >= mean - 2*std`, assert no ANOMALY; for `avg_oee < mean - 2*std`, assert ANOMALY fires
  - [ ] 5.5 Run all tests and confirm they pass
