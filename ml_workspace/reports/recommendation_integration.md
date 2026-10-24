# Интеграция multiple-candidate ranking

`ml_workspace/recommendation/ranker.py` реализует отдельный Top-K prototype. Сначала применяются hard filters: work type, context-dependent material role, stock, room compatibility, required properties и optional max price. Затем suitability объединяет applicability, room evidence и независимый quality score. Цена не повышает quality; в budget strategy она служит ограничением/тай-брейкером. Missing quality data явно возвращается в результате.

Output содержит product ID, suitability score, price, reasons и `missing_quality_data`. Furniture/outdoor товары не попадают в material estimate без требуемых work type + role.

Для backend безопасная интеграция возможна как новый adapter/service: `CatalogRepo.candidates` формирует кандидатов, prototype ранжирует, а существующий `RatingRanker.rank` пока не меняется. Для полного объяснимого результата понадобятся новые DTO для material role relation, hard constraints, quality evidence и ranked alternatives; это schema change и требует одобрения. Полный budget optimizer не реализован.
