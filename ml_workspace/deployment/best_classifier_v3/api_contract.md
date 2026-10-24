# API contract

`load_model(path, "taxonomy_v2", trusted=True)` returns a process-cacheable `ModelBundle`.
`predict(model, product)` returns one `Prediction`; a sequence returns a list.

`ProductInput.name` is required and non-empty. Optional fields are `product_id`, `source_category`,
`category_names`, `description`, `marketing_description`, `characteristics`, `price`, `sale_unit`,
and `brand_name`. Missing optional fields become empty values. `characteristics` accepts a mapping
or a list of mappings. Inference does not read training data.

`Prediction.work_types` and its compatibility alias `labels` are lists and are never reduced to a
single label. `scores` contains every work-type probability. `dimension_scores` also includes
domain, activity, product-category, work-type, and room scores. `status` is `predicted`,
`uncertain`, or `non_renovation`; low domain confidence clears downstream labels. Returned work
types satisfy their saved thresholds. The dataclass is JSON serializable through `dataclasses.asdict`.

The backend adapter preserves the existing `Suggestion` schema. Unsupported strict backend enums
cannot enter `work_types`/`room_types`; each is exposed as
`flags["unsupported_work_type__<label>"]` or `flags["unsupported_room_type__<label>"]`.
