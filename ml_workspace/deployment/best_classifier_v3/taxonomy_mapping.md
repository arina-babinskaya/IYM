# Taxonomy-to-backend mapping

Canonical model labels remain unchanged in `taxonomy_v2`.

- Exact backend work IDs map directly.
- `plumbing_fixture_install` maps to backend `plumbing_install`.
- `floor_covering_install` maps to `laminate_laying` or `linoleum_laying` only when product text
  identifies the material; otherwise it is explicitly flagged as unsupported.
- `ventilation_install`, `heating_climate_install`, `door_window_install`, `lighting_install`, and
  `decorative_finish_install` have no backend `WorkType` enum and are flagged.
- Rooms map directly except `living_room -> living`; `dining_room`, `home_office`, `utility_room`,
  and `general_indoor` are flagged as unsupported.
- Unambiguous product categories map to backend materials. Unknown or unsupported categories use
  `Material.other`; this is a compatibility fallback, not a model label rewrite.

The implementation is in `app/ml/tfidf.py`. Ranking inputs, ordering, and algorithms are untouched.
