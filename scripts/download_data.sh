#!/usr/bin/env bash
# Downloads the raw Olist Brazilian E-Commerce Public Dataset (original release: Kaggle, CC BY-NC-SA 4.0)
# from a Hugging Face mirror whose file sizes match the original Kaggle release byte-for-byte.
# Original source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
set -euo pipefail
mkdir -p data_raw
BASE="https://huggingface.co/datasets/bulutttt/olist-raw-data/resolve/main"
for f in olist_customers_dataset.csv olist_order_items_dataset.csv olist_order_payments_dataset.csv \
         olist_order_reviews_dataset.csv olist_orders_dataset.csv olist_products_dataset.csv \
         olist_sellers_dataset.csv product_category_name_translation.csv; do
  curl -sL -o "data_raw/$f" "$BASE/$f"
  echo "downloaded $f"
done
