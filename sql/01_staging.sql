-- =====================================================================
-- STAGING LAYER: one cleaned view per raw table.
-- Rules: cast types, standardize values, deduplicate, never drop silently
-- (anything removed here is counted in dq_checks.sql).
-- =====================================================================

DROP VIEW IF EXISTS stg_orders;
CREATE VIEW stg_orders AS
SELECT
    order_id,
    customer_id,
    order_status,
    datetime(order_purchase_timestamp)        AS purchase_ts,
    datetime(order_approved_at)               AS approved_ts,
    datetime(order_delivered_carrier_date)    AS shipped_ts,
    datetime(order_delivered_customer_date)   AS delivered_ts,
    date(order_estimated_delivery_date)       AS estimated_delivery_date,
    strftime('%Y-%m', order_purchase_timestamp) AS purchase_month
FROM raw_orders;

DROP VIEW IF EXISTS stg_customers;
CREATE VIEW stg_customers AS
SELECT customer_id, customer_unique_id, customer_state, customer_city
FROM raw_customers;

-- Payments: 'not_defined' type and 0 installments are data errors -> standardized
DROP VIEW IF EXISTS stg_payments;
CREATE VIEW stg_payments AS
SELECT
    order_id,
    payment_sequential,
    CASE WHEN payment_type = 'not_defined' THEN 'unknown' ELSE payment_type END AS payment_type,
    CASE WHEN payment_installments < 1 THEN 1 ELSE payment_installments END    AS installments,
    CAST(payment_value AS REAL) AS payment_value
FROM raw_payments;

DROP VIEW IF EXISTS stg_items;
CREATE VIEW stg_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    CAST(i.price AS REAL)         AS price,
    CAST(i.freight_value AS REAL) AS freight_value,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category
FROM raw_items i
LEFT JOIN raw_products p ON p.product_id = i.product_id
LEFT JOIN raw_category_translation t ON t.product_category_name = p.product_category_name;

-- Reviews: some orders have several reviews and some review_ids repeat.
-- Keep the most recently answered review per order (window function dedup).
DROP VIEW IF EXISTS stg_reviews;
CREATE VIEW stg_reviews AS
SELECT order_id, review_score, review_comment_message, review_creation_date
FROM (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY order_id
            ORDER BY review_answer_timestamp DESC, review_creation_date DESC
        ) AS rn
    FROM raw_reviews r
)
WHERE rn = 1;
