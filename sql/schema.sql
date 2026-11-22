CREATE TABLE IF NOT EXISTS products (
    product_id BIGINT PRIMARY KEY CHECK (product_id > 0),
    title TEXT NOT NULL CHECK (btrim(title) <> ''),
    category TEXT NOT NULL CHECK (btrim(category) <> ''),
    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    stock INTEGER CHECK (stock >= 0),
    brand TEXT,
    rating NUMERIC(3, 2) CHECK (rating BETWEEN 0 AND 5)
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGINT PRIMARY KEY CHECK (customer_id > 0),
    customer_name TEXT,
    customer_email TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT PRIMARY KEY CHECK (order_id > 0),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    order_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGINT PRIMARY KEY CHECK (order_item_id > 0),
    order_id BIGINT NOT NULL REFERENCES orders(order_id),
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price > 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);
