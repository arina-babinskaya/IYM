# Maxidom full-catalog analysis

Analysis date: 2026-10-29. Source: `requirments/products_final.json` (SHA-256 should be recorded by the data owner when transferring it to Drive).

## Dataset shape

- 88,790 product records; all have `id`, `cod_good`, and a non-empty `name`.
- Fields: `id`, `cod_good`, `name`, `marketing_description`, `url_key`, `price`, `currency`, `brand`, `collection`, `country`, `categories`, `unit`, `description`, `weight`, and `characteristics`.
- Missing: marketing description 14,181 (16.0%), description 266 (0.3%), characteristics 9,439 (10.6%), brand 27,940 (31.5%), collection 69,008 (77.7%), country 2,018 (2.3%). No names or category mappings are missing.
- `categories` is always present but contains exactly one entry per product. Thus the export has no usable hierarchy, only 2,421 IDs resolving to 2,375 distinct names. Forty-six IDs are aliases/name collisions requiring source-system clarification.
- There are 2,375 distinct source category names. 1,070 have at most 10 products, 633 at most 5, and 296 at most 2. Treating each raw category as a class is unsuitable.

## Distribution

Largest source categories (actual counts):

| Source category | Products |
|---|---:|
| Фасады - МДФ | 2,084 |
| Обои | 1,297 |
| Фитинги | 1,254 |
| Семена овощей | 1,177 |
| Керамогранит напольный | 951 |
| Саморезы, шурупы | 946 |
| Семена цветов | 864 |
| Кашпо, горшки для комнатных растений | 807 |
| Люстры потолочные | 803 |
| Луковичные цветы | 710 |
| Комплектующие к плинтусам | 657 |
| Шторы рулонные | 640 |
| Тарелки | 603 |
| Плитка настенная для ванной | 577 |
| Саженцы | 573 |
| Двери межкомнатные | 572 |
| Мебельные ручки | 548 |
| Лампы светодиодные | 536 |
| Болты, гайки, винты, шайбы | 517 |
| Люстры потолочные светодиодные | 516 |

The complete, auditable distribution and selected mapping is in `taxonomy/source_category_mapping.csv`; it includes all 2,421 source IDs and counts.

## Names and duplicates

After case/punctuation/whitespace normalization, 1,072 rows belong to a duplicated-name group (500 groups; largest group 12). Splits group these normalized names, also removing long SKU-like numeric tokens. This is a conservative near-duplicate proxy; image-based and manufacturer-part-number similarity are unavailable. Validation/test rows are never synthesized or duplicated.

Product names are generally short commercial phrases containing product type, brand, dimensions, and variant. This supports combined word (1–2 gram) and character (3–5 gram) TF-IDF. Character features handle Russian morphology, spelling variations such as `Бpa`, transliteration, and model codes.

## Reuse, merge, split, clarify

- Reuse semantically clean families (e.g. seeds, wallpaper, fasteners) but map them to stable IDs independent of source wording.
- Merge low-volume variants such as vegetable/flower seeds into `garden.seeds`, chandelier variants into `lighting.indoor`, and raw screw/bolt categories into `hardware.fasteners`.
- Keep distinctions supported by volume and customer meaning: indoor/outdoor/decorative lighting; wall/floor/mosaic tile; paint/primer/putty; tableware/cookware.
- Source categories whose names combine unrelated concepts trigger conflicting rules and are excluded from supervised loss.
- Generic or unmatched source labels require clarification rather than being silently forced into a precise category.

Contradictions between a category and product text cannot establish ground truth automatically. The review queue preserves name, descriptions, characteristics, source category, candidate labels and reason. A future human audit should sample confident labels as well as conflicts.

## Major-family coverage and examples

Counts below are from the generated training split (not the whole catalog); examples are literal catalog names and are useful for auditing weak-label noise.

| Family | Train rows | Example |
|---|---:|---|
| auto | 285 | фильтр масляный FINWHALE LF101 |
| building | 981 | гидроизоляция PLITONIT Гидроэласт 4кг |
| cleaning | 397 | порошок стиральный NORDLAND Eco 1,8кг |
| doors_windows | 1,260 | дверь жалюзийная 394х1805мм |
| electrical | 2,168 | выключатель 1-клавишный HEGEL Alfa |
| finishing | 2,551 | краска TIKKIVALA Metallista по ржавчине |
| flooring | 1,516 | плинтус потолочный СОЛИД 60х58х2000мм |
| furniture | 2,214 | столик придиванный Haushalt |
| garden | 4,835 | семена огурец Зеленый поток |
| hardware | 1,754 | анкер клиновой оцинкованный 8x90мм |
| heating | 994 | радиатор биметаллический RT10-500F2 |
| home | 4,033 | контейнер ПОЛИМЕРБЫТ 10л |
| kitchen | 2,716 | набор бокалов CRYSTAL BOHEMIA |
| lighting | 4,193 | светильник светодиодный Leek Бриллиант |
| outdoor | 566 | щепа для копчения Piktime 400г |
| pets | 167 | корм для кошек PRIME Adult |
| plumbing | 2,830 | водорозетка полипропиленовая PRO AQUA |
| seasonal | 229 | ель срезанная в сетке Россия |
| tile | 1,609 | плитка настенная ALMA CERAMICA Style |
| tools | 1,650 | пилки для лобзика KENDO T101BF |

The source-driven sample also exposes candidates for human audit (for example, a ceiling plinth entering the broader flooring-accessories family). This is why test scores must be described only as agreement with weak labels.

## Coverage

The v1 deterministic rules confidently map 52,738 products (59.4%). A further 7,432 have conflicting source-rule evidence and 28,620 have no accepted mapping; all 36,052 receive `review.unresolved` and are excluded from training and headline evaluation. Coverage is deliberately reported separately from supervised eligibility. The 82 business leaf labels plus one non-trainable review leaf cover every record operationally.
