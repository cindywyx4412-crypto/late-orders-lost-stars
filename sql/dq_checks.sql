-- =====================================================================
-- DATA QUALITY CHECKS. Each check returns one row:
--   check_name | layer | severity | failing_rows | total_rows | description
-- severity: 'error' blocks the pipeline, 'warn' is logged and handled.
-- =====================================================================
SELECT 'orders_pk_unique' AS check_name, 'raw' AS layer, 'error' AS severity,
       COUNT(*) - COUNT(DISTINCT order_id) AS failing_rows, COUNT(*) AS total_rows,
       'order_id must be unique in orders' AS description
FROM raw_orders
UNION ALL
SELECT 'payments_type_not_defined', 'raw', 'warn',
       SUM(payment_type = 'not_defined'), COUNT(*),
       'payment_type = not_defined (mapped to unknown in staging)'
FROM raw_payments
UNION ALL
SELECT 'payments_zero_installments', 'raw', 'warn',
       SUM(payment_installments < 1), COUNT(*),
       'installments < 1 (floored to 1 in staging)'
FROM raw_payments
UNION ALL
SELECT 'reviews_duplicate_review_id', 'raw', 'warn',
       COUNT(*) - COUNT(DISTINCT review_id), COUNT(*),
       'review_id appears more than once'
FROM raw_reviews
UNION ALL
SELECT 'reviews_multiple_per_order', 'raw', 'warn',
       COUNT(*) - COUNT(DISTINCT order_id), COUNT(*),
       'extra reviews per order (deduplicated to latest in staging)'
FROM raw_reviews
UNION ALL
SELECT 'orders_without_items', 'raw', 'warn',
       SUM(order_id NOT IN (SELECT order_id FROM raw_items)), COUNT(*),
       'orders with no line items (mostly canceled/unavailable)'
FROM raw_orders
UNION ALL
SELECT 'orders_without_payment', 'raw', 'warn',
       SUM(order_id NOT IN (SELECT order_id FROM raw_payments)), COUNT(*),
       'orders with no payment record'
FROM raw_orders
UNION ALL
SELECT 'items_orphan_seller', 'raw', 'error',
       SUM(seller_id NOT IN (SELECT seller_id FROM raw_sellers)), COUNT(*),
       'order items referencing an unknown seller'
FROM raw_items
UNION ALL
SELECT 'orders_orphan_customer', 'raw', 'error',
       SUM(customer_id NOT IN (SELECT customer_id FROM raw_customers)), COUNT(*),
       'orders referencing an unknown customer'
FROM raw_orders
UNION ALL
SELECT 'delivered_missing_timestamp', 'raw', 'warn',
       SUM(order_status = 'delivered' AND order_delivered_customer_date IS NULL), COUNT(*),
       'status delivered but no delivery timestamp'
FROM raw_orders
UNION ALL
SELECT 'delivered_before_purchase', 'raw', 'error',
       SUM(order_delivered_customer_date < order_purchase_timestamp), COUNT(*),
       'delivery timestamp earlier than purchase timestamp'
FROM raw_orders
UNION ALL
SELECT 'approved_before_purchase', 'raw', 'error',
       SUM(order_approved_at < order_purchase_timestamp), COUNT(*),
       'payment approved before the order was placed'
FROM raw_orders
UNION ALL
SELECT 'mart_orders_row_count', 'mart', 'error',
       ABS((SELECT COUNT(*) FROM fct_orders) - (SELECT COUNT(*) FROM raw_orders)), (SELECT COUNT(*) FROM raw_orders),
       'fct_orders must keep exactly one row per raw order (no fan-out from joins)'
UNION ALL
SELECT 'recon_payment_vs_order_value', 'mart', 'warn',
       SUM(ABS(recon_diff) > 1.00), SUM(recon_diff IS NOT NULL),
       'payment total differs from items + freight by more than R$1'
FROM fct_orders;
