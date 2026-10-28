-- =====================================================================
-- MART LAYER: analysis-ready tables. Materialized as tables for speed.
-- =====================================================================

-- ---------- order-level payments summary ----------
DROP TABLE IF EXISTS int_order_payments;
CREATE TABLE int_order_payments AS
WITH ranked AS (
    SELECT
        order_id, payment_type, installments, payment_value,
        ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC, payment_sequential) AS rn
    FROM stg_payments
)
SELECT
    order_id,
    MAX(CASE WHEN rn = 1 THEN payment_type END)             AS primary_payment_type,
    MAX(installments)                                       AS max_installments,
    SUM(payment_value)                                      AS payment_total,
    COUNT(*)                                                AS payment_count,
    MAX(CASE WHEN payment_type = 'voucher' THEN 1 ELSE 0 END) AS used_voucher
FROM ranked
GROUP BY order_id;

-- ---------- order-level items summary ----------
DROP TABLE IF EXISTS int_order_items;
CREATE TABLE int_order_items AS
WITH ranked AS (
    SELECT
        order_id, seller_id, category, price, freight_value,
        ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY price DESC, order_item_id) AS rn
    FROM stg_items
)
SELECT
    order_id,
    SUM(price)                                   AS items_value,
    SUM(freight_value)                           AS freight_value,
    COUNT(*)                                     AS item_count,
    COUNT(DISTINCT seller_id)                    AS seller_count,
    MAX(CASE WHEN rn = 1 THEN seller_id END)     AS primary_seller_id,
    MAX(CASE WHEN rn = 1 THEN category END)      AS primary_category
FROM ranked
GROUP BY order_id;

-- ---------- fct_orders: one row per order ----------
DROP TABLE IF EXISTS fct_orders;
CREATE TABLE fct_orders AS
SELECT
    o.order_id,
    c.customer_unique_id,
    c.customer_state,
    o.order_status,
    o.purchase_ts,
    o.purchase_month,
    o.approved_ts,
    o.delivered_ts,
    o.estimated_delivery_date,
    -- payment
    p.primary_payment_type,
    p.max_installments,
    p.payment_total,
    p.payment_count,
    p.used_voucher,
    -- items
    i.items_value,
    i.freight_value,
    i.item_count,
    i.seller_count,
    i.primary_seller_id,
    i.primary_category,
    -- derived: payment approval lag
    CASE WHEN o.approved_ts IS NOT NULL
         THEN (julianday(o.approved_ts) - julianday(o.purchase_ts)) * 24.0 END   AS approval_lag_hours,
    -- derived: fulfilment
    CASE WHEN o.order_status IN ('canceled', 'unavailable') THEN 1 ELSE 0 END    AS is_canceled,
    CASE WHEN o.delivered_ts IS NOT NULL AND o.order_status = 'delivered' THEN 1 ELSE 0 END AS is_delivered,
    CASE WHEN o.delivered_ts IS NOT NULL
         THEN julianday(o.delivered_ts) - julianday(o.purchase_ts) END            AS delivery_days,
    CASE WHEN o.delivered_ts IS NOT NULL AND o.order_status = 'delivered'
         THEN CASE WHEN date(o.delivered_ts) > o.estimated_delivery_date THEN 1 ELSE 0 END END AS is_late,
    CASE WHEN o.delivered_ts IS NOT NULL
         THEN julianday(date(o.delivered_ts)) - julianday(o.estimated_delivery_date) END AS days_vs_estimate,
    -- customer experience
    r.review_score,
    CASE WHEN r.review_score IS NOT NULL THEN CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END END AS is_low_review,
    r.review_comment_message,
    -- reconciliation: what the customer paid vs what the order is worth
    ROUND(p.payment_total - (i.items_value + i.freight_value), 2)                AS recon_diff,
    -- order sequence per customer (for repeat-purchase analysis)
    ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id ORDER BY o.purchase_ts) AS customer_order_seq
FROM stg_orders o
LEFT JOIN stg_customers     c ON c.customer_id = o.customer_id
LEFT JOIN int_order_payments p ON p.order_id = o.order_id
LEFT JOIN int_order_items    i ON i.order_id = o.order_id
LEFT JOIN stg_reviews        r ON r.order_id = o.order_id;

CREATE INDEX idx_fct_orders_month  ON fct_orders(purchase_month);
CREATE INDEX idx_fct_orders_cust   ON fct_orders(customer_unique_id);
CREATE INDEX idx_fct_orders_seller ON fct_orders(primary_seller_id);

-- ---------- customer-level: did the customer come back? ----------
DROP TABLE IF EXISTS dim_customers;
CREATE TABLE dim_customers AS
WITH firsts AS (
    SELECT * FROM fct_orders WHERE customer_order_seq = 1
),
nexts AS (
    SELECT customer_unique_id, MIN(purchase_ts) AS second_purchase_ts
    FROM fct_orders WHERE customer_order_seq = 2
    GROUP BY customer_unique_id
)
SELECT
    f.customer_unique_id,
    f.customer_state,
    f.order_id              AS first_order_id,
    f.purchase_ts           AS first_purchase_ts,
    f.purchase_month        AS first_purchase_month,
    f.primary_payment_type  AS first_payment_type,
    f.primary_category      AS first_category,
    f.items_value           AS first_items_value,
    f.is_late               AS first_order_late,
    f.review_score          AS first_review_score,
    n.second_purchase_ts,
    CASE WHEN n.second_purchase_ts IS NOT NULL
          AND julianday(n.second_purchase_ts) - julianday(f.purchase_ts) <= 180
         THEN 1 ELSE 0 END  AS repurchased_180d
FROM firsts f
LEFT JOIN nexts n USING (customer_unique_id);

-- ---------- seller-level health scorecard ----------
DROP TABLE IF EXISTS dim_sellers;
CREATE TABLE dim_sellers AS
SELECT
    i.seller_id,
    s.seller_state,
    COUNT(DISTINCT i.order_id)                                         AS orders,
    ROUND(SUM(CASE WHEN o.is_canceled = 0 THEN i.price END), 2)        AS gmv,   -- same definition as metric 'gmv'
    AVG(o.is_late)                                                     AS late_rate,
    AVG(o.is_low_review)                                               AS low_review_rate,
    AVG(o.is_canceled)                                                 AS cancel_rate,
    AVG(o.review_score)                                                AS avg_review,
    MIN(o.purchase_ts)                                                 AS first_sale_ts,
    MAX(o.purchase_ts)                                                 AS last_sale_ts
FROM stg_items i
JOIN fct_orders o ON o.order_id = i.order_id
LEFT JOIN raw_sellers s ON s.seller_id = i.seller_id
WHERE o.purchase_month BETWEEN '2017-01' AND '2018-08'
GROUP BY i.seller_id, s.seller_state;
