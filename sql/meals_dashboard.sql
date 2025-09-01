-- Ensure the meals table includes a dedup_key column
-- Replace `PROJECT_ID` and `DATASET` with actual values
ALTER TABLE `PROJECT_ID.DATASET.meals`
ADD COLUMN IF NOT EXISTS dedup_key STRING;

-- View for dashboard queries that exposes dedup_key
CREATE OR REPLACE VIEW `PROJECT_ID.DATASET.meals_dashboard` AS
SELECT
  user_id,
  when_date,
  image_base64,
  kcal,
  dedup_key
FROM `PROJECT_ID.DATASET.meals`;
