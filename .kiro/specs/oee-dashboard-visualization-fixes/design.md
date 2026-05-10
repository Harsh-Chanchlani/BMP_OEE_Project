# OEE Dashboard Visualization Fixes — Bugfix Design

## Overview

Three independent bugs degrade the OEE dashboard's readability and correctness:

1. **Y-axis label overlap** — `width={44}` on the `YAxis` in the OEE TREND `LineChart` and SPC Control Chart is too narrow to render both the rotated axis label and the percentage tick values without clipping/overlap. Fix: increase `width` to `60` and left margin from `10` to `20` in both charts.

2. **Sudden OEE value jumps** — `setOeeData(msg.data)` in `useOeeWebSocket.js` replaces the entire state array on every WebSocket push. Because Spark's sliding windows overlap and `ON CONFLICT DO UPDATE` allows re-writing existing rows, previously-rendered values can change, causing visible jumps. Fix: merge incoming windows into existing state by matching on `(machine_id, window_start, window_end)`.

3. **False ANOMALY alerts** — In `write_batch`, `_compute_spc` runs first and inserts SPC statistics that include the current batch's `avg_oee` values. `_detect_anomalies` then fetches that freshly-inserted row and compares each window against a mean that already contains that same window — a circular dependency. Fix: in `_detect_anomalies`, fetch only SPC rows where `calculated_at < batch_ts`.

Each fix is minimal and targeted. No chart layout, WebSocket protocol, or Spark topology changes are required beyond the specific lines described.

---

## Glossary

- **Bug_Condition (C)**: The condition that triggers a bug — the specific input or state that causes incorrect behaviour.
- **Property (P)**: The desired correct behaviour when the bug condition holds.
- **Preservation**: Existing correct behaviour that must remain unchanged after the fix.
- **`isBugCondition(input)`**: Pseudocode predicate that returns `true` when the bug is triggered.
- **`expectedBehavior(result)`**: Pseudocode predicate that returns `true` when the output is correct.
- **`write_batch(batch_df, batch_id)`**: The PySpark `foreachBatch` callback in `backend/spark_oee_stream.py` that upserts OEE windows, computes SPC stats, and runs anomaly detection.
- **`_compute_spc(conn, machine_id, batch_ts)`**: Helper that inserts a new `spc_data` row using the last 24 h of `oee_data`.
- **`_detect_anomalies(conn, rows, ap)`**: Helper that fetches the latest `spc_data` row and raises ANOMALY alerts.
- **`useOeeWebSocket()`**: React hook in `oee-dashboard/src/hooks/useOeeWebSocket.js` that maintains the `oeeData` state array.
- **`oeeData`**: The React state array of OEE window objects, keyed by `(machine_id, window_start, window_end)`.
- **`batch_ts`**: The `datetime.utcnow()` timestamp captured at the start of analytics helpers in `write_batch`.
- **Sliding window**: Spark 1-minute window with 30-second slide — windows overlap, so a single event can appear in two consecutive windows.

---

## Bug Details

### Bug 1 — Y-axis Label Overlap

#### Bug Condition

The bug manifests when either the OEE TREND `LineChart` or the SPC Control Chart renders with `width={44}` on the `YAxis`. The 44 px budget is consumed by the tick labels (e.g. `"84%"`, `"85%"`) leaving no room for the rotated `"OEE (%)"` axis label, which clips or overlaps the ticks.

**Formal Specification:**
```
FUNCTION isBugCondition_1(chart)
  INPUT: chart — a Recharts LineChart instance
  OUTPUT: boolean

  RETURN chart.YAxis.width == 44
         AND chart.YAxis.label IS NOT NULL
         AND chart.margin.left <= 10
END FUNCTION
```

**Examples:**
- OEE TREND chart renders with `width={44}` and `margin={{ left: 10 }}` → "OEE (%)" label overlaps "84%" tick.
- SPC Control Chart renders with `width={44}` and `margin={{ left: 10 }}` → "OEE (%)" label overlaps tick values.
- APQ BarChart renders with `width={44}` but uses label `"Component (%)"` — same narrow budget but not in scope of this fix (separate chart, lower visual impact).

---

### Bug 2 — Sudden OEE Value Jumps

#### Bug Condition

The bug manifests when the WebSocket delivers an `oee_update` message and `setOeeData(msg.data)` replaces the entire `oeeData` array. If Spark has recomputed `avg_oee` for an existing `(machine_id, window_start, window_end)` row (due to late-arriving data or watermark advancement), the new array contains a different value for that key, causing the chart to jump.

**Formal Specification:**
```
FUNCTION isBugCondition_2(prevState, incomingMsg)
  INPUT: prevState    — current oeeData array
         incomingMsg  — WebSocket message with type "oee_update"
  OUTPUT: boolean

  existingKeys  := { (r.machine_id, r.window_start, r.window_end) | r IN prevState }
  incomingKeys  := { (r.machine_id, r.window_start, r.window_end) | r IN incomingMsg.data }
  overlapping   := existingKeys INTERSECT incomingKeys

  RETURN EXISTS key IN overlapping
         WHERE prevState[key].avg_oee != incomingMsg.data[key].avg_oee
END FUNCTION
```

**Examples:**
- Window `(LITHO_ASML_01, 10:00:00, 10:01:00)` was rendered at `avg_oee = 73.5`. Spark recomputes it to `74.2` due to a late event. Next WebSocket push replaces the array → chart jumps from 73.5 to 74.2.
- Window `(ETCH_LAM_02, 10:00:30, 10:01:30)` overlaps with the previous window. Both are in the incoming array. Full replacement causes both to update simultaneously → two-point jump.
- New window arrives for a machine with no prior state → no jump (not a bug condition).

---

### Bug 3 — False ANOMALY Alerts

#### Bug Condition

The bug manifests when `write_batch` calls `_compute_spc` before `_detect_anomalies`. `_compute_spc` inserts a `spc_data` row using `oee_data` rows that include the current batch's windows. `_detect_anomalies` then fetches that row (`ORDER BY calculated_at DESC LIMIT 1`) and computes `threshold = mean - 2 * std` using a mean that already incorporates the window being evaluated — a circular dependency that inflates the mean and narrows the standard deviation, causing borderline windows to appear anomalous.

**Formal Specification:**
```
FUNCTION isBugCondition_3(row, spc_row, batch_ts)
  INPUT: row      — an OEE window row from the current batch
         spc_row  — the SPC row fetched by _detect_anomalies
         batch_ts — the timestamp passed to _compute_spc
  OUTPUT: boolean

  RETURN spc_row.calculated_at >= batch_ts
         AND row.avg_oee IS INCLUDED IN spc_row.sample
         AND row.avg_oee < (spc_row.mean_value - 2 * spc_row.std_dev)
END FUNCTION
```

**Examples:**
- `LITHO_ASML_01`: `avg_oee = 84.84`, contaminated `mean = 84.9`, `std = 0.03` → `threshold = 84.84` → false ANOMALY.
- `INSPECT_KLA_05`: `avg_oee = 86.74`, contaminated `mean = 87.1`, `std = 0.18` → `threshold = 86.74` → false ANOMALY.
- Machine with `avg_oee` well below historical mean → genuine anomaly, unaffected by the fix.
- Machine with fewer than 10 windows → `_compute_spc` skips, `_detect_anomalies` finds no SPC row → no alert (correct, unchanged).

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Mouse clicks, tooltips, and hover states on all charts must continue to work exactly as before.
- The APQ BarChart, Six Big Losses chart, Fleet View area charts, and Machine Comparison panel are not touched and must render identically.
- WARNING and CRITICAL threshold alerts (triggered by `avg_oee < WARN_THR` or `< CRIT_THR`) must continue to fire correctly.
- The WebSocket reconnection logic and authentication flow in `useOeeWebSocket.js` must remain unchanged.
- New OEE windows that have never been seen before must still be appended to `oeeData` correctly.
- SPC computation (`_compute_spc`) itself is unchanged — only the query in `_detect_anomalies` is modified.
- Shift performance upserts and loss category writes are unaffected.
- The `isAnimationActive={false}` setting on trend lines must remain to prevent animation on data updates.

**Scope:**
All inputs that do NOT match the three bug conditions above should be completely unaffected by these fixes. This includes:
- All chart interactions (zoom, tooltip, legend toggle).
- All REST API calls (stats, APQ, SPC endpoint, losses, machine comparison).
- All Spark streaming topology, windowing parameters, and Kafka configuration.
- All database schema and existing data.

---

## Hypothesized Root Cause

### Bug 1 — Y-axis Label Overlap

1. **Insufficient `width` budget**: Recharts allocates exactly `width` pixels for the entire left axis area, including tick labels and the rotated axis label. At `width={44}`, the `"84%"` tick text (~28 px at 11 px font) plus the rotated `"OEE (%)"` label (~40 px) exceed the budget.
2. **Insufficient left margin**: `margin={{ left: 10 }}` provides no additional breathing room between the axis area and the chart boundary, compounding the overlap.

### Bug 2 — Sudden OEE Value Jumps

1. **Full-array replacement**: `setOeeData(msg.data)` discards all previous state and replaces it with the server's current snapshot. Any window whose `avg_oee` changed between pushes will cause a visible chart jump.
2. **Spark sliding window recomputation**: The 1-minute / 30-second slide means windows overlap. Late-arriving events or watermark advancement can cause Spark to recompute `avg_oee` for a window that was already written, triggering `ON CONFLICT DO UPDATE` in `write_batch`.
3. **No client-side deduplication**: The hook has no merge logic — it trusts the server snapshot completely.

### Bug 3 — False ANOMALY Alerts

1. **Execution order in `write_batch`**: `_compute_spc` is called before `_detect_anomalies`. The SPC row inserted by `_compute_spc` uses `oee_data` rows that include the current batch (just upserted moments earlier in the same `write_batch` call).
2. **`ORDER BY calculated_at DESC LIMIT 1` fetches the contaminated row**: `_detect_anomalies` always fetches the most recent SPC row, which is the one just inserted by `_compute_spc` in the same batch.
3. **Circular dependency**: The window being evaluated for anomaly detection is part of the sample used to compute the mean and standard deviation against which it is evaluated.

---

## Correctness Properties

Property 1: Bug Condition — Y-axis Labels Render Without Overlap

_For any_ OEE TREND LineChart or SPC Control Chart render where the chart has a rotated Y-axis label and percentage tick values, the fixed component SHALL display both the axis label and all tick values fully visible and non-overlapping within the allocated axis width.

**Validates: Requirements 2.1**

Property 2: Bug Condition — WebSocket Merge Prevents Visual Jumps

_For any_ WebSocket `oee_update` message where incoming windows overlap with existing `oeeData` state (same `machine_id`, `window_start`, `window_end`), the fixed hook SHALL update only the changed windows in-place rather than replacing the entire array, so that chart re-renders reflect only genuine value changes.

**Validates: Requirements 2.2**

Property 3: Bug Condition — Anomaly Detection Uses Pre-batch SPC Stats

_For any_ call to `_detect_anomalies` within `write_batch`, the fixed function SHALL fetch only SPC statistics rows where `calculated_at < batch_ts`, ensuring the anomaly threshold is computed from historical data that does not include the current batch's windows.

**Validates: Requirements 2.3**

Property 4: Preservation — Non-bug Inputs Unchanged

_For any_ input where none of the three bug conditions hold (charts with adequate width, WebSocket messages with no overlapping window updates, anomaly detection on machines with no circular SPC dependency), the fixed code SHALL produce exactly the same behaviour as the original code, preserving all existing chart rendering, alerting, and data-flow functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

---

## Fix Implementation

### Bug 1 — Y-axis Label Overlap

**File**: `oee-dashboard/src/App.jsx`

**Locations**:
1. OEE TREND `LineChart` — inside the `{/* Row 2: OEE Trend */}` block (~line 793)
2. SPC Control Chart — inside `SpcChart` component (~line 310)

**Specific Changes**:
1. **OEE TREND chart `YAxis`**: Change `width={44}` → `width={60}`.
2. **OEE TREND chart `LineChart` margin**: Change `margin={{ top: 10, right: 60, bottom: 30, left: 10 }}` → `margin={{ top: 10, right: 60, bottom: 30, left: 20 }}`.
3. **SPC Control Chart `YAxis`**: Change `width={44}` → `width={60}`.
4. **SPC Control Chart `LineChart` margin**: Change `margin={{ top: 10, right: 60, bottom: 30, left: 10 }}` → `margin={{ top: 10, right: 60, bottom: 30, left: 20 }}`.

No other charts are modified (APQ BarChart, Fleet View area charts, and Six Big Losses chart are out of scope).

---

### Bug 2 — Sudden OEE Value Jumps

**File**: `oee-dashboard/src/hooks/useOeeWebSocket.js`

**Function**: `ws.onmessage` handler

**Specific Changes**:

Replace the single-line replacement:
```js
if (msg.type === "oee_update") setOeeData(msg.data);
```

With a merge that upserts by composite key:
```js
if (msg.type === "oee_update") {
  setOeeData((prev) => {
    const map = new Map(
      prev.map((r) => [`${r.machine_id}|${r.window_start}|${r.window_end}`, r])
    );
    for (const r of msg.data) {
      map.set(`${r.machine_id}|${r.window_start}|${r.window_end}`, r);
    }
    return Array.from(map.values());
  });
}
```

This ensures:
- Existing windows whose `avg_oee` changed are updated in-place (no jump from full replacement).
- New windows are appended.
- Windows no longer present in the server snapshot are retained (they represent valid historical data within the 30-minute window).

---

### Bug 3 — False ANOMALY Alerts

**File**: `backend/spark_oee_stream.py`

**Function**: `_detect_anomalies(conn, rows, ap)`

**Specific Changes**:

Replace the SPC fetch query:
```python
cur.execute("""
    SELECT mean_value, std_dev FROM spc_data
    WHERE machine_id = %s AND metric = 'oee'
    ORDER BY calculated_at DESC LIMIT 1;
""", (row.machine_id,))
```

With a query that excludes the current batch's SPC row:
```python
cur.execute("""
    SELECT mean_value, std_dev FROM spc_data
    WHERE machine_id = %s AND metric = 'oee'
      AND calculated_at < %s
    ORDER BY calculated_at DESC LIMIT 1;
""", (row.machine_id, batch_ts))
```

This requires passing `batch_ts` into `_detect_anomalies`. Update the call site in `write_batch`:
```python
# Before:
_detect_anomalies(conn, rows, alert_producer)

# After:
_detect_anomalies(conn, rows, alert_producer, batch_ts)
```

And update the function signature:
```python
# Before:
def _detect_anomalies(conn, rows, ap):

# After:
def _detect_anomalies(conn, rows, ap, batch_ts):
```

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate each bug on unfixed code, then verify the fix works correctly and preserves existing behaviour.

---

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate each bug BEFORE implementing the fix. Confirm or refute the root cause analysis.

**Bug 1 — Y-axis Overlap**

**Test Plan**: Render the OEE TREND and SPC charts in a test environment with `width={44}` and assert that the axis label bounding box does not overlap the tick label bounding boxes.

**Test Cases**:
1. **OEE TREND axis width test**: Render `LineChart` with `width={44}` and a label — assert no overlap (will fail on unfixed code).
2. **SPC chart axis width test**: Render `SpcChart` with `width={44}` and a label — assert no overlap (will fail on unfixed code).

**Expected Counterexamples**:
- Axis label and tick text occupy overlapping pixel regions at `width={44}`.

---

**Bug 2 — OEE Value Jumps**

**Test Plan**: Simulate two sequential WebSocket messages where the second message contains an updated `avg_oee` for an existing window. Assert that the state update does not cause a full-array replacement.

**Test Cases**:
1. **Overlapping window update**: Send initial state with window `(M1, T1, T2, oee=73.5)`, then send update with same key but `oee=74.2`. Assert `oeeData` still contains exactly one entry for that key with `oee=74.2` (will fail on unfixed code — full replacement produces a jump).
2. **New window append**: Send initial state, then send update with a new window key. Assert the new window is appended and existing windows are unchanged.
3. **Multiple machines**: Send update with windows for two machines. Assert both are present in state.

**Expected Counterexamples**:
- Full replacement causes chart to re-render all points, including changed values, producing visible jumps.

---

**Bug 3 — False ANOMALY Alerts**

**Test Plan**: Set up a mock database with `oee_data` and `spc_data` rows. Call `write_batch` with a batch that includes a window whose `avg_oee` is close to the contaminated mean. Assert that no ANOMALY alert is raised when the window's value is within the pre-batch historical range.

**Test Cases**:
1. **Contaminated SPC fetch**: Insert a `spc_data` row with `calculated_at = batch_ts` (same timestamp). Call `_detect_anomalies` with the unfixed query. Assert it fetches the contaminated row (will demonstrate the bug).
2. **LITHO_ASML_01 false positive**: `avg_oee=84.84`, contaminated `mean=84.9`, `std=0.03` → `threshold=84.84` → ANOMALY raised (will fail on unfixed code — should not alert).
3. **INSPECT_KLA_05 false positive**: `avg_oee=86.74`, contaminated `mean=87.1`, `std=0.18` → `threshold=86.74` → ANOMALY raised (will fail on unfixed code).

**Expected Counterexamples**:
- `_detect_anomalies` fetches the SPC row inserted in the same `write_batch` call, producing a threshold that incorrectly flags borderline windows.

---

### Fix Checking

**Goal**: Verify that for all inputs where each bug condition holds, the fixed code produces the expected behaviour.

**Bug 1:**
```
FOR ALL chart WHERE isBugCondition_1(chart) DO
  render(chart_with_width_60_and_left_margin_20)
  ASSERT axisLabel.boundingBox DOES NOT INTERSECT tickLabels.boundingBoxes
END FOR
```

**Bug 2:**
```
FOR ALL (prevState, incomingMsg) WHERE isBugCondition_2(prevState, incomingMsg) DO
  newState := mergeOeeData(prevState, incomingMsg.data)
  ASSERT newState[key].avg_oee == incomingMsg.data[key].avg_oee  -- updated
  ASSERT COUNT(newState) >= COUNT(prevState)                      -- no data loss
  ASSERT no full-array replacement occurred
END FOR
```

**Bug 3:**
```
FOR ALL (row, batch_ts) WHERE isBugCondition_3(row, spc_row, batch_ts) DO
  spc_row := fetchSpc(machine_id, calculated_at < batch_ts)
  IF spc_row IS NULL THEN
    ASSERT no ANOMALY alert raised
  ELSE
    threshold := spc_row.mean_value - 2 * spc_row.std_dev
    ASSERT row.avg_oee >= threshold  -- no false positive
  END IF
END FOR
```

---

### Preservation Checking

**Goal**: Verify that for all inputs where the bug conditions do NOT hold, the fixed code produces the same result as the original code.

```
FOR ALL input WHERE NOT isBugCondition_1(input)
                AND NOT isBugCondition_2(input)
                AND NOT isBugCondition_3(input) DO
  ASSERT original_behaviour(input) == fixed_behaviour(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for Bug 2 preservation checking because:
- It generates many random `(prevState, incomingMsg)` pairs automatically.
- It catches edge cases (empty state, single machine, all-new windows) that manual tests might miss.
- It provides strong guarantees that the merge logic never drops or corrupts windows that are not part of the bug condition.

**Test Cases**:
1. **No-overlap WebSocket push**: Send a message with entirely new window keys. Assert all previous windows are retained and new ones are appended.
2. **WARNING/CRITICAL alerts unaffected**: Verify that `avg_oee < WARN_THR` still triggers WARNING/CRITICAL alerts after the `_detect_anomalies` signature change.
3. **SPC endpoint unaffected**: Verify the REST `/api/spc` endpoint returns the same data before and after the fix.
4. **Chart tooltip preservation**: Verify tooltip values match `oeeData` entries after merge.
5. **Genuine anomaly still detected**: Verify that a window with `avg_oee` genuinely below `mean - 2*std` (using pre-batch SPC stats) still raises an ANOMALY alert.

---

### Unit Tests

- Test `mergeOeeData` (extracted helper or inline logic) with overlapping, new, and empty inputs.
- Test `_detect_anomalies` with `calculated_at < batch_ts` filter: assert it skips the current-batch SPC row.
- Test `_detect_anomalies` with no pre-batch SPC row: assert no alert is raised.
- Test OEE TREND `YAxis` renders with `width={60}` and `left=20` margin.
- Test SPC `YAxis` renders with `width={60}` and `left=20` margin.

### Property-Based Tests

- Generate random arrays of OEE windows and random incoming WebSocket payloads; assert the merged result contains all keys from both inputs and no key is lost.
- Generate random `(avg_oee, mean, std)` triples where `avg_oee >= mean - 2*std`; assert no ANOMALY alert is raised when using pre-batch SPC stats.
- Generate random `(avg_oee, mean, std)` triples where `avg_oee < mean - 2*std`; assert ANOMALY alert IS raised (genuine anomaly preserved).

### Integration Tests

- Full `write_batch` call with a mock DB: assert `_detect_anomalies` never fetches a `spc_data` row with `calculated_at >= batch_ts`.
- WebSocket end-to-end: connect hook, receive two sequential messages with an overlapping window update, assert chart data array has no duplicate keys and the updated value is reflected.
- Visual regression: render OEE TREND and SPC charts with realistic data and assert axis labels are fully within their allocated bounds.
