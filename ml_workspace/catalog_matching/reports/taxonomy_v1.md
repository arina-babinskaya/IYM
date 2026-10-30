# Catalog taxonomy v1

`catalog-taxonomy-v1` is an independent website-oriented product taxonomy. It has 82 trainable leaves under 20 display parents, plus `review.unresolved`. Parent labels are derived from a leaf and are not model targets.

Definitions and exclusions are machine-readable in `taxonomy/catalog_taxonomy.py`. The source mapping is versioned in `taxonomy/source_category_mapping.csv`. Rule priority and conflict behavior are in `preprocessing/weak_labeling.py`.

Design principles: stable English dot-separated IDs; Russian display names; one leaf per product; no renovation stages/work types; meaningful merges where raw classes are sparse; explicit review instead of a dominant semantic “other”. Major examples include `garden.seeds` (seeds/bulbs), `lighting.outdoor` (weather-oriented fixtures), `kitchen.tableware` (serving vessels), and `tools.accessories` (bits/discs/drills, excluding the powered tool itself).

V1 coverage: 52,738 confident rows across all 82 trainable leaves. Several leaves still have low support after conservative conflict filtering; the notebook reports support before fitting and the split manifest records the limitation.
