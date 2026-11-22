SELECT p.product_id, p.title,
       COALESCE(SUM(oi.quantity * oi.unit_price), 0)::NUMERIC(16, 2) AS total_sales
FROM products AS p
LEFT JOIN order_items AS oi ON oi.product_id = p.product_id
GROUP BY p.product_id, p.title
ORDER BY total_sales DESC, p.product_id;
