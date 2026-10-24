#!/usr/bin/env python3
"""Ready-to-run pandas exploration examples for reviewers."""

import json
import pandas as pd

clean = pd.read_csv("ml_workspace/data/products_clean.csv", keep_default_na=False)
labels = pd.read_csv("ml_workspace/data/products_multidim_weak_labeled.csv", keep_default_na=False)
df = clean.merge(labels, on="product_id", validate="one_to_one")

print("Распределение семейств:\n", df.primary_product_family.value_counts().head(25))
print("\nНеизвестные work types:\n", df[df.work_type_status == "unknown_needs_review"][["product_id", "name", "source_category"]].head(20))
print("\nMulti-room:\n", df[df.proposed_room_types.map(lambda x: len(json.loads(x)) > 1)][["product_id", "name", "proposed_room_types"]].head(20))
print("\nПример характеристик:\n", df[["product_id", "name", "important_attributes_json"]].head(10))
