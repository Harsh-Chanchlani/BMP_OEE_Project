# OEE Dashboard — Remaining Tasks

---

## 1. Infrastructure Fixes

- [ ] 1.1 Update `ccloud-python-client/client.properties` with new Confluent Cloud API key, secret, and bootstrap server
- [ ] 1.2 Delete stale Spark checkpoints (`/tmp/oee_spark_checkpoint` and `/tmp/oee_spark_raw_checkpoint`)
- [ ] 1.3 Verify `.env` bootstrap server matches the new Confluent Cloud cluster URL

---

## 2. Backend — Missing Analytics & Forecasting

### 2.1 ARIMA Forecasting
- [ ] 2.1.1 Add `statsmodels` to `requirements.txt`
- [ ] 2.1.2 Add `/api/oee/forecast?machine=X&steps=10` endpoint in `api.py` — fits ARIMA(1,1,1) on last 50 OEE windows from `oee_data`, returns predicted values with 95% confidence intervals, writes results to `oee_predictions` table
- [ ] 2.1.3 Add `/api/oee/forecast/accuracy?machine=X` endpoint — compares past predictions vs actuals from `oee_predictions` table

### 2.2 Shift Performance (data exists, no API response used in frontend)
- [ ] 2.2.1 Verify `/api/shifts` returns correct data with all columns (avg_oee, min_oee, max_oee, avg_availability, avg_performance, avg_quality, data_points)

### 2.3 Enhanced Alerts
- [ ] 2.3.1 Enrich `/api/alerts` response to include `machine_description` field — a static map in `api.py` that describes each machine (e.g. "LITHO_ASML_01: EUV Lithography scanner — 7nm logic wafer exposure tool")
- [ ] 2.3.2 Add `loss_context` field to alert response — join with `loss_categories` to show what loss event was active during the alert window
- [ ] 2.3.3 Add `/api/alerts/summary` endpoint — returns count by level (WARNING, CRITICAL, ANOMALY) and top 3 most-alerted machines in last 24h

### 2.4 SPC Enhancements
- [ ] 2.4.1 Compute and return `cp` and `cpk` in `/api/spc` response (already stored in `spc_data` table, just not returned)

---

## 3. Frontend Redesign — Industrial Dark Theme + Sidebar Layout

### 3.1 Theme & Global Styles
- [ ] 3.1.1 Replace `index.css` — deep navy/slate background (`#0a0e1a`), blue/teal accent palette (`#38bdf8`, `#0ea5e9`), Inter font via Google Fonts, CSS variables for the full color system
- [ ] 3.1.2 Replace `App.css` with layout utility classes (sidebar width, content area, card base styles)

### 3.2 Layout & Navigation
- [ ] 3.2.1 Build `Sidebar.jsx` — fixed left sidebar with nav items: Overview, Machine Detail, Alerts, Analytics. Active state highlight, machine name badge at bottom, collapse button
- [ ] 3.2.2 Build `Header.jsx` — top bar with logo ("BMP OEE"), machine selector dropdown, live WebSocket status dot, last-refresh timestamp, logout button
- [ ] 3.2.3 Wire sidebar + header into `App.jsx` with a `currentPage` state, render correct page component based on selection

### 3.3 Shared Components
- [ ] 3.3.1 Build `InfoTooltip.jsx` — a reusable `ⓘ` icon that shows a tooltip/popover with explanatory text when hovered. Used on every chart and KPI card
- [ ] 3.3.2 Build `KpiCard.jsx` — stat card with accent border-left stripe, label, large number, unit, trend arrow (up/down vs previous window), and InfoTooltip
- [ ] 3.3.3 Build `ChartCard.jsx` — wrapper card with title, optional subtitle, InfoTooltip icon in top-right corner, consistent padding and border style
- [ ] 3.3.4 Build `MachineDescription.jsx` — small panel showing machine name, type, role in fab process, and current status badge. Used in Machine Detail and Alerts pages

### 3.4 Overview Page (`OverviewPage.jsx`)
- [ ] 3.4.1 Top row: 4 KPI cards — Fleet Average OEE, Active Alerts count, Machines Above 85%, Machines Below 60%
- [ ] 3.4.2 Machine comparison grid — one card per machine showing OEE gauge mini, A/P/Q bars, status badge, machine description one-liner
- [ ] 3.4.3 Live OEE sparkline per machine (last 20 windows) using WebSocket data

### 3.5 Machine Detail Page (`MachineDetailPage.jsx`)
- [ ] 3.5.1 Machine description panel at top — full name, what the machine does, current shift, current lot
- [ ] 3.5.2 OEE gauge + KPI row (Latest OEE, 24h Avg, 24h Min, 24h Max, Total Windows, Cp/Cpk)
- [ ] 3.5.3 OEE Trend chart with InfoTooltip: "This chart shows 1-minute windowed OEE averages computed by Spark Structured Streaming with a 30-second slide. Reference lines show World Class (85%) and Good (75%) thresholds."
- [ ] 3.5.4 APQ Breakdown bar chart with InfoTooltip: "Availability × Performance × Quality = OEE. Each bar shows the component value per time window. A drop in any component directly reduces OEE."
- [ ] 3.5.5 SPC Control Chart with InfoTooltip: "Statistical Process Control chart. UCL/LCL are ±3σ from the rolling mean. Points outside these limits (shown in red) indicate the process is out of statistical control."
- [ ] 3.5.6 ARIMA Forecast chart — shows last 30 actual OEE windows + next 10 predicted windows with shaded 95% confidence interval band. InfoTooltip: "ARIMA(1,1,1) model fitted on recent OEE history. Shaded area shows 95% prediction interval. Use this to anticipate degradation before it occurs."
- [ ] 3.5.7 Shift Performance table — rows per shift (morning/afternoon/night), columns: Avg OEE, Min, Max, A/P/Q, Data Points. InfoTooltip: "Aggregated OEE performance broken down by production shift. Helps identify if a specific shift consistently underperforms."

### 3.6 Alerts Page (`AlertsPage.jsx`)
- [ ] 3.6.1 Summary bar at top — total unacknowledged, count by level (WARNING / CRITICAL / ANOMALY), top alerted machine
- [ ] 3.6.2 Full alert table with columns: Time, Machine, Level badge, OEE value, Threshold, Loss Context, Machine Description, Acknowledge button
- [ ] 3.6.3 Each alert row expandable — shows machine description ("EUV Lithography scanner..."), what the loss event was, and a plain-English explanation of the alert condition
- [ ] 3.6.4 Filter bar — filter by machine, alert level, acknowledged/unacknowledged

### 3.7 Analytics Page (`AnalyticsPage.jsx`)
- [ ] 3.7.1 Six Big Losses Pareto chart with InfoTooltip: "Pareto analysis of the Six Big Losses (SEMI E10). The bar chart shows total loss % per category; the line shows cumulative %. Focus improvement efforts on the leftmost bars."
- [ ] 3.7.2 Shift performance heatmap/table — all machines × all shifts, color-coded by OEE level. InfoTooltip: "Cross-machine shift comparison. Green = World Class (≥85%), Yellow = Good (≥75%), Red = Poor (<60%)."
- [ ] 3.7.3 SPC summary table — all machines, showing Mean, Std Dev, UCL, LCL, Cp, Cpk. InfoTooltip: "Cp measures process spread vs spec width. Cpk accounts for centering. Cpk ≥ 1.33 is generally considered capable."
- [ ] 3.7.4 ARIMA forecast comparison — all machines side by side, showing current OEE vs predicted OEE in next 10 windows, with trend direction arrow

### 3.8 Login Screen
- [ ] 3.8.1 Redesign login — centered card on navy background, BMP logo/wordmark, clean sans-serif inputs, industrial accent color, sign in / sign up toggle

---

## 4. Optional / Post-Demo

- [ ]* Implement real MinIO/S3 data lake write path in Spark
- [ ]* Add per-service Confluent Cloud API keys (producer, Spark, API each get their own)
- [ ]* Track ARIMA forecast accuracy over time using `oee_predictions.actual_oee` backfill
- [ ]* Populate `downtime_events` table from Spark loss event detection
