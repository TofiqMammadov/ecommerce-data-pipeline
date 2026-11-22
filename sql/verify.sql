-- Row counts (compare with the source files; do not assume fixed values).
SELECT 'products' AS table_name, COUNT(*) AS row_count FROM products
UNION ALL SELECT 'customers', COUNT(*) FROM customers
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items;

-- All three orphan counts must be zero.
SELECT
  (SELECT COUNT(*) FROM orders o LEFT JOIN customers c USING (customer_id)
   WHERE c.customer_id IS NULL) AS orders_without_customers,
  (SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o USING (order_id)
   WHERE o.order_id IS NULL) AS items_without_orders,
  (SELECT COUNT(*) FROM order_items oi LEFT JOIN products p USING (product_id)
   WHERE p.product_id IS NULL) AS items_without_products;

SELECT COALESCE(SUM(quantity * unit_price), 0)::NUMERIC(16, 2) AS total_sales
FROM order_items;
