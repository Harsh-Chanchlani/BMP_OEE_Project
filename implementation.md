# OEE System Enhancement Implementation Plan

This document outlines the detailed steps required to enhance the BMP OEE Project architecture and analysis, directly inspired by the methodologies described in *"Understanding, Measuring, and Improving Overall Equipment Effectiveness"* by Ross Kenneth Kennedy.

---

## Phase 1: Technical Implementation

### 1. Upgrade to the "7 Losses" Model
The book mandates shifting from the traditional "Six Big Losses" to a "7 Losses" model by explicitly categorizing **Planned Downtime** (e.g., scheduled maintenance, shift changes) under Availability losses.

**Action Items:**
*   **Producer Update (`producer/Producer.py`):**
    *   Introduce a new state `STATUS_PLANNED_DOWNTIME` alongside existing states (`RUNNING`, `DOWN`, `WARNING`).
    *   Modify the simulation logic to periodically enter `STATUS_PLANNED_DOWNTIME` for scheduled intervals (e.g., simulating a 30-minute shift handover every 8 simulated hours).
    *   Ensure the JSON payload emitted to Kafka includes a specific flag or category for `planned_downtime`.
*   **Backend Update (`backend/`):**
    *   Update the database schema/queries to parse and store `planned_downtime` as a distinct metric separate from `unplanned_downtime`.
*   **Frontend Dashboard Update (`oee-dashboard/`):**
    *   Update the "Big Losses" visualization component to "7 Big Losses."
    *   Render "Planned Downtime" distinctively (e.g., with a neutral color like gray or blue) so it is not confused with unexpected breakdowns (red).

### 2. Implement the "Time-Loss" Pareto View
Kennedy emphasizes that actionable continuous improvement is driven by analyzing actual *time lost*, rather than just OEE percentages. 

**Action Items:**
*   **Data Aggregation:** Ensure the backend calculates and exposes the exact duration (in minutes or hours) lost to each of the 7 loss categories over a given time window (e.g., current shift, last 24 hours).
*   **React Component (`oee-dashboard/src/components/`):**
    *   Create a new component: `TimeLossParetoChart.js` (using Recharts, Chart.js, or similar).
    *   The chart must be a Pareto Chart (bars sorted in descending order of time lost, accompanied by a cumulative percentage line).
    *   **X-Axis:** The 7 Loss Categories.
    *   **Y-Axis (Primary):** Time Lost (Minutes).
    *   **Y-Axis (Secondary):** Cumulative Percentage.
*   **Integration:** Add this view prominently to the main dashboard or as a dedicated "Loss Analysis" tab.

### 3. Operator Annotation for "Minor Unrecorded Stoppages" (Second-Level Analysis)
Automation captures *when* a machine stops, but operators provide the context of *why*. This bridges automated telemetry with human insight.

**Action Items:**
*   **Backend API:** Create a new REST endpoint (e.g., `POST /api/annotations`) that accepts `timestamp`, `machine_id`, `anomaly_type`, and `operator_notes`.
*   **Frontend UI:**
    *   Enhance the existing HTC Control Graph so that when an anomaly (temperature spike/drop) or a minor stoppage occurs, an operator can click on that specific data point.
    *   Open a modal allowing the operator to input notes (e.g., "Sensor Calibration Issue," "Jammed Wafer").
    *   Save this annotation to the backend and overlay it on the graph as a visible marker for future shifts and analysts.

---

## Phase 2: Analytical Enhancements (For the Final Report)

### 4. Custom Business Baselines vs. Generic Benchmarks
*   **Task:** Do not default to the generic "85% World Class OEE" metric.
*   **Execution:** Dedicate a subsection in the report that defines the simulated system's *Baseline OEE* over a 24-hour period. Propose a custom, realistic *Target OEE* specifically tailored for semiconductor fabrication, arguing that maximizing quality yield is more critical than raw speed in this context.

### 5. Tiered Analysis Structure
Structure Section 7 of the Final Report based on Kennedy's methodology:
*   **First-Level Analysis (Macro/Fleet View):** Analyze the aggregated Availability, Performance, and Quality across the entire fleet. Discuss how this gives plant management a high-level view of capacity and overall health.
*   **Second-Level Analysis (Micro/Root-Cause View):** Drill down into the specific HTC Control Graph of a single machine. Show how the specific telemetry correlates directly with the specific performance/quality losses identified in the First-Level view.

### 6. Financial Cost-Benefit Correlation
*   **Task:** Translate technical OEE improvements into business value (Chapter 5, Sheet 7).
*   **Execution:** Create a hypothetical Cost-Benefit analysis in the report. For example: "A 1% drop in the Quality Rate due to late anomaly detection results in $250,000 of scrapped silicon wafers per month. The implemented real-time Kafka architecture detects anomalies 15 minutes faster than legacy systems, directly preventing this financial loss."

### 7. Evaluation of the "Automated Data Capture" Architecture
*   **Task:** Evaluate the project's technical stack against the book's Chapter 6 criteria.
*   **Execution:** Write a section evaluating the project's *Information Design* and *Accessibility*. Discuss how WebSockets and React provide immediate accessibility to loss data compared to end-of-shift paper reports, thereby enabling the exact type of rapid, continuous improvement Kennedy advocates.
