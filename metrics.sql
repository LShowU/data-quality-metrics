-- Executive metrics
SELECT COUNT(*) AS order_count,
       ROUND(COALESCE(SUM(quantity * unit_price), 0), 2) AS gmv,
       ROUND(COALESCE(SUM(quantity * unit_price) / NULLIF(COUNT(*), 0), 0), 2) AS average_order_value,
       COUNT(DISTINCT customer_id) AS customer_count,
       ROUND(COALESCE(SUM(quantity), 0), 1) AS units
FROM orders;

-- Daily trend
SELECT order_date, COUNT(*) AS order_count,
       ROUND(SUM(quantity * unit_price), 2) AS gmv,
       ROUND(SUM(quantity * unit_price) / NULLIF(COUNT(*), 0), 2) AS average_order_value
FROM orders GROUP BY order_date ORDER BY order_date;

-- Product leaderboard
SELECT product_id, COUNT(*) AS order_count,
       SUM(quantity) AS units, ROUND(SUM(quantity * unit_price), 2) AS gmv
FROM orders GROUP BY product_id ORDER BY gmv DESC;

-- Data quality and lineage
SELECT source_file, COUNT(*) AS loaded_rows, MIN(loaded_at) AS first_loaded_at,
       MAX(loaded_at) AS last_loaded_at FROM orders GROUP BY source_file;
SELECT rule, column_name, COUNT(*) AS exception_count
FROM quarantine GROUP BY rule, column_name ORDER BY exception_count DESC;
