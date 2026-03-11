CREATE TABLE IF NOT EXISTS oee_data (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  window_start TIMESTAMP NOT NULL,
  window_end TIMESTAMP NOT NULL,
  avg_oee DOUBLE PRECISION NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oee_data_window_start
  ON oee_data (window_start);

CREATE INDEX IF NOT EXISTS idx_oee_data_machine_window
  ON oee_data (machine_id, window_start);
