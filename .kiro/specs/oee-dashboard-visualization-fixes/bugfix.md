# Bugfix Requirements Document

## Introduction

The OEE dashboard visualization system has three critical bugs affecting data readability and accuracy. These bugs impact the user's ability to monitor OEE performance effectively and may lead to incorrect operational decisions. The issues involve Y-axis label rendering problems caused by insufficient axis width, unexpected OEE value jumps caused by Spark sliding window recalculation combined with full-array WebSocket replacement, and false ANOMALY alerts caused by a circular dependency in the SPC statistics computation pipeline.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the OEE TREND LineChart (App.jsx) or SPC Control Chart renders THEN the Y-axis label "OEE (%)" (rotated -90°, `position: "insideLeft"`, `offset: 12`) overlaps the percentage tick values (e.g. "84%", "85%") because `width={44}` is too narrow to accommodate both the rotated axis label and the formatted tick text within the 10px left margin

1.2 WHEN the WebSocket pushes an updated batch of OEE windows and `setOeeData(msg.data)` replaces the entire `oeeData` array THEN the OEE TREND chart and sparkline display sudden value jumps (e.g. 73% → 77%) because Spark's 1-minute sliding window with 30-second slide causes overlapping windows to share data points, and the `ON CONFLICT DO UPDATE SET avg_oee = EXCLUDED.avg_oee` upsert in `write_batch` allows previously-written window values to be overwritten when Spark recomputes them due to late-arriving data or watermark advancement

1.3 WHEN `write_batch` processes a new Spark micro-batch THEN `_compute_spc` is called first and inserts a new `spc_data` row using the current batch's `avg_oee` values (including the window being evaluated), after which `_detect_anomalies` fetches that newly-inserted SPC row and compares each window's `avg_oee` against a mean that already includes that same window — causing false ANOMALY alerts for machines like LITHO_ASML_01 (OEE: 84.84% vs threshold: 84.9%) and INSPECT_KLA_05 (OEE: 86.74% vs threshold: 87.1%) where the OEE is close to the contaminated mean

### Expected Behavior (Correct)

2.1 WHEN the OEE TREND LineChart or SPC Control Chart renders THEN the system SHALL display the Y-axis with sufficient `width` (e.g. 60px) so that the rotated "OEE (%)" label and percentage tick values are fully visible without overlapping

2.2 WHEN the WebSocket pushes updated OEE window data THEN the system SHALL merge incoming windows into the existing `oeeData` state by matching on `(machine_id, window_start, window_end)` rather than replacing the entire array, so that chart re-renders reflect only genuine value changes and do not produce visual jumps from window recomputation

2.3 WHEN `write_batch` runs anomaly detection THEN the system SHALL compute the anomaly threshold using SPC statistics derived exclusively from historical `oee_data` rows with `window_start` strictly before the current batch's earliest `window_start`, excluding the current batch's data from the mean and standard deviation calculation

### Unchanged Behavior (Regression Prevention)

3.1 WHEN OEE data is within normal ranges THEN the system SHALL CONTINUE TO display charts and visualizations correctly without rendering issues

3.2 WHEN legitimate OEE threshold alerts (WARNING/CRITICAL) are triggered by `avg_oee` falling below `WARN_THR` or `CRIT_THR` in `write_batch` THEN the system SHALL CONTINUE TO generate and display these alerts properly

3.3 WHEN users interact with chart tooltips and hover states THEN the system SHALL CONTINUE TO show accurate data values and timestamps

3.4 WHEN the WebSocket connection provides real-time OEE updates THEN the system SHALL CONTINUE TO update visualizations smoothly without data corruption or loss of existing window history

3.5 WHEN multiple machines are displayed in fleet view THEN the system SHALL CONTINUE TO render individual machine charts correctly without cross-contamination

3.6 WHEN fewer than 10 OEE windows exist for a machine THEN the system SHALL CONTINUE TO skip SPC computation and anomaly detection for that machine
