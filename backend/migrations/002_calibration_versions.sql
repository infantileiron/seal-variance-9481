-- Calibration rules, immutable computation versions and schema upgrade for
-- installations created from 001_initial.sql.  The application also applies this
-- at startup through src/config/upgrade.py.
CREATE TABLE IF NOT EXISTS calibration_rules(
  id SERIAL PRIMARY KEY,
  code_start VARCHAR(50) NOT NULL,
  code_end VARCHAR(50) NOT NULL,
  revision INTEGER NOT NULL,
  points JSON NOT NULL,
  note TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  impact_scope JSON,
  created_by VARCHAR(120) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  CONSTRAINT uq_calibration_range_revision UNIQUE(code_start,code_end,revision)
);
CREATE TABLE IF NOT EXISTS assessment_versions(
  id SERIAL PRIMARY KEY,
  assessment_id INTEGER NOT NULL REFERENCES assessments(id),
  version INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL,
  calibration_fingerprint VARCHAR(64) NOT NULL,
  calibration_snapshot JSON,
  result JSON,
  quarantine JSON,
  error TEXT NOT NULL,
  trigger VARCHAR(40) NOT NULL,
  requested_by VARCHAR(120) NOT NULL,
  published BOOLEAN NOT NULL,
  stale BOOLEAN NOT NULL,
  superseded BOOLEAN NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  started_at VARCHAR(40) NOT NULL,
  completed_at VARCHAR(40) NOT NULL,
  CONSTRAINT uq_assessment_version UNIQUE(assessment_id,version),
  CONSTRAINT uq_assessment_calibration UNIQUE(assessment_id,calibration_fingerprint)
);
ALTER TABLE assessments ADD COLUMN IF NOT EXISTS current_version_id INTEGER;
ALTER TABLE assessments ADD COLUMN IF NOT EXISTS approved_version_id INTEGER;
ALTER TABLE assessments ADD COLUMN IF NOT EXISTS recommendation_version_id INTEGER;
ALTER TABLE assessments ADD COLUMN IF NOT EXISTS candidate_version_id INTEGER;
ALTER TABLE assessments ADD COLUMN IF NOT EXISTS stale BOOLEAN NOT NULL DEFAULT FALSE;
