-- ============================================
-- OEE DATA SCHEMA - Enhanced for Analytics
-- ============================================

-- Main OEE data table (enhanced with component breakdown)
CREATE TABLE IF NOT EXISTS oee_data (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  window_start TIMESTAMP NOT NULL,
  window_end TIMESTAMP NOT NULL,
  avg_oee DOUBLE PRECISION NOT NULL,
  avg_availability DOUBLE PRECISION,
  avg_performance DOUBLE PRECISION,
  avg_quality DOUBLE PRECISION,
  shift TEXT,  -- 'morning', 'afternoon', 'night'
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oee_data_window_start
  ON oee_data (window_start);

CREATE INDEX IF NOT EXISTS idx_oee_data_machine_window
  ON oee_data (machine_id, window_start);

CREATE INDEX IF NOT EXISTS idx_oee_data_shift
  ON oee_data (machine_id, shift, window_start);

-- ============================================
-- DOWNTIME EVENTS - For downtime detection
-- ============================================
CREATE TABLE IF NOT EXISTS downtime_events (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  start_time TIMESTAMP NOT NULL,
  end_time TIMESTAMP,
  duration_minutes DOUBLE PRECISION,
  category TEXT NOT NULL,  -- 'planned', 'unplanned', 'micro_stop'
  loss_type TEXT,  -- 'equipment_failure', 'setup_adjustment', 'idling', 'reduced_speed', 'defects', 'reduced_yield'
  severity TEXT DEFAULT 'warning',  -- 'warning', 'critical'
  root_cause TEXT,
  oee_before DOUBLE PRECISION,
  oee_during DOUBLE PRECISION,
  is_resolved BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_downtime_machine_time
  ON downtime_events (machine_id, start_time DESC);

CREATE INDEX IF NOT EXISTS idx_downtime_category
  ON downtime_events (category, loss_type);

CREATE INDEX IF NOT EXISTS idx_downtime_unresolved
  ON downtime_events (machine_id, is_resolved) WHERE is_resolved = FALSE;

-- ============================================
-- SHIFT PERFORMANCE - Aggregated by shift
-- ============================================
CREATE TABLE IF NOT EXISTS shift_performance (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  shift_date DATE NOT NULL,
  shift TEXT NOT NULL,  -- 'morning', 'afternoon', 'night'
  avg_oee DOUBLE PRECISION NOT NULL,
  avg_availability DOUBLE PRECISION,
  avg_performance DOUBLE PRECISION,
  avg_quality DOUBLE PRECISION,
  min_oee DOUBLE PRECISION,
  max_oee DOUBLE PRECISION,
  total_downtime_minutes DOUBLE PRECISION DEFAULT 0,
  data_points INTEGER DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(machine_id, shift_date, shift)
);

CREATE INDEX IF NOT EXISTS idx_shift_perf_machine_date
  ON shift_performance (machine_id, shift_date DESC);

CREATE INDEX IF NOT EXISTS idx_shift_perf_shift
  ON shift_performance (shift, shift_date);

-- ============================================
-- LOSS CATEGORIES - Six Big Losses tracking
-- ============================================
CREATE TABLE IF NOT EXISTS loss_categories (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  loss_type TEXT NOT NULL,  -- Six Big Losses
  loss_component TEXT NOT NULL,  -- 'availability', 'performance', 'quality'
  loss_percentage DOUBLE PRECISION NOT NULL,
  loss_minutes DOUBLE PRECISION,
  description TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loss_machine_time
  ON loss_categories (machine_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_loss_type
  ON loss_categories (loss_type);

-- ============================================
-- OEE PREDICTIONS - ML forecasting results
-- ============================================
CREATE TABLE IF NOT EXISTS oee_predictions (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  prediction_time TIMESTAMP NOT NULL,  -- when prediction was made
  target_time TIMESTAMP NOT NULL,  -- what time the prediction is for
  predicted_oee DOUBLE PRECISION NOT NULL,
  confidence_lower DOUBLE PRECISION,
  confidence_upper DOUBLE PRECISION,
  model_type TEXT DEFAULT 'exponential_smoothing',
  actual_oee DOUBLE PRECISION,  -- filled in later for accuracy tracking
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pred_machine_target
  ON oee_predictions (machine_id, target_time DESC);

-- ============================================
-- SPC CONTROL DATA - Statistical Process Control
-- ============================================
CREATE TABLE IF NOT EXISTS spc_data (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  calculated_at TIMESTAMP NOT NULL,
  metric TEXT NOT NULL,  -- 'oee', 'availability', 'performance', 'quality'
  mean_value DOUBLE PRECISION NOT NULL,
  std_dev DOUBLE PRECISION NOT NULL,
  ucl DOUBLE PRECISION NOT NULL,  -- Upper Control Limit (mean + 3*std)
  lcl DOUBLE PRECISION NOT NULL,  -- Lower Control Limit (mean - 3*std)
  usl DOUBLE PRECISION,  -- Upper Specification Limit
  lsl DOUBLE PRECISION,  -- Lower Specification Limit
  cp DOUBLE PRECISION,   -- Process Capability
  cpk DOUBLE PRECISION,  -- Process Capability Index
  sample_size INTEGER,
  out_of_control_count INTEGER DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spc_machine_time
  ON spc_data (machine_id, calculated_at DESC);

-- ============================================
-- ALERT HISTORY - Enhanced alerting
-- ============================================
CREATE TABLE IF NOT EXISTS alert_history (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  alert_time TIMESTAMP NOT NULL,
  alert_type TEXT NOT NULL,  -- 'threshold', 'anomaly', 'spc_violation', 'prediction'
  severity TEXT NOT NULL,  -- 'info', 'warning', 'critical'
  message TEXT NOT NULL,
  metric_value DOUBLE PRECISION,
  threshold_value DOUBLE PRECISION,
  context JSONB,  -- Additional context data
  acknowledged BOOLEAN DEFAULT FALSE,
  acknowledged_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_machine_time
  ON alert_history (machine_id, alert_time DESC);

CREATE INDEX IF NOT EXISTS idx_alert_unacknowledged
  ON alert_history (machine_id, acknowledged) WHERE acknowledged = FALSE;

-- ============================================
-- UPGRADE 3 - OEE ALERTS
-- ============================================
CREATE TABLE IF NOT EXISTS oee_alerts (
    id          BIGSERIAL PRIMARY KEY,
    machine_id  TEXT NOT NULL,
    avg_oee     DOUBLE PRECISION NOT NULL,
    threshold   DOUBLE PRECISION NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end   TIMESTAMP NOT NULL,
    alert_level TEXT NOT NULL,        -- 'WARNING' or 'CRITICAL'
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oee_alerts_machine_time
    ON oee_alerts (machine_id, window_start);
CREATE INDEX IF NOT EXISTS idx_oee_alerts_unacked
    ON oee_alerts (acknowledged) WHERE acknowledged = FALSE;
