# Product matching and optional GigaChat integration

Date: 2026-10-28. No production bindings were regenerated and no paid GigaChat call was made.

## Root causes and deterministic result

The catalog has 88,790 active, priced, in-stock rows. The previous adapter mapped only ten ML
product categories, used only the maximum work score as binding confidence, and rejected
`Material.other`. Thus a sound material prediction without a work label became confidence zero.
It also lacked lighting, doors/windows, heating, ventilation and decorative families.

The adapter now uses separate domain/category evidence for binding confidence, retains work scores
for work decisions, maps the supported backend families, disambiguates selected accessories from
product/category text, infers a work only when `works_for_material()` has exactly one consequence,
and rejects work/material conflicts. Electrical frames and terminals remain unbound because the
backend has no dedicated estimate material slot; they are not mislabeled as switches or cable.

A read-only inference over all 88,790 database products with threshold 0.8 produced:

| Measurement | Count |
|---|---:|
| Reported old production baseline | 8,396 |
| Recomputed approximation of old policy | 7,822 |
| New deterministic publishable bindings | 12,039 |
| Increase over reported baseline | 3,643 (+43.4%) |
| Non-renovation rejected | 21,689 |
| Unmapped/unrelated retained for review or rejection | 41,309 |
| Recognized material below threshold | 11,714 |
| Work/material conflicts | 2,039 |

Largest newly supported publishable groups include lighting 2,640, doors 1,037, decorative 1,074,
heating 434 and ventilation 368. These are prospective counts: existing DB bindings were not
overwritten. Regeneration must be an explicit operational decision.

## Correctness checks

The complete automated suite passes: 137 passed, 1 skipped. Tests cover the real artifact path,
lighting support, material confidence without work output, taxonomy consistency, strict GigaChat
JSON, OAuth headers, persistent cache and conflict-to-review behavior. Existing artifact metrics
measure agreement with weak labels and are not independent real-world precision.

A small human-readable spot check of newly enabled groups found correct radiators, luminaires,
doors, ventilation grilles, laminate and decorative panels. It also found frames and a terminal
that would contaminate switch/cable candidates; explicit exclusions were added before the final
12,039 count. The repository contains no completed manually reviewed gold sample, so a defensible
manual precision number cannot be reported yet. The next required validation is a blinded,
stratified review of at least 200 newly publishable and 100 rejected/uncertain products.

## First GigaChat pilot: exact failure analysis

The cache contains all 30 HTTP-successful responses: 22 schema-valid results and eight
post-response failures. There were no API/network/authentication failures in these eight.

| Products | Exact cause | Count |
|---|---|---:|
| 2212 | Completion ended inside `evidence` at the token limit; invalid JSON | 1 |
| 19450 | Invented material `polypropylene` | 1 |
| 19538, 38867, 46053 | String `none` instead of JSON null/omission | 3 |
| 21692 | Invented material `dsp` | 1 |
| 73697 | Material label `socket` used as a product category | 1 |
| 24886 | Valid `electrical_goods` category-only result rejected by the old material-required rule | 1 |

Product 50894 was schema-valid but contradictory (`primer` category with `paint` material); the
revised policy abstains. The 22 valid results consumed 22,606 tokens, while all 30 responses
reported **34,109 tokens**. Validation-first aggregation therefore omitted 11,503 tokens.

## GigaChat fallback

`scripts/gigachat_fallback.py` operates only on unbound renovation/unknown candidates. It defaults
to a no-call dry run, has an explicit limit (25), sequential execution, SQLite response cache,
resume-by-cache, attempt-level accounting, retries/backoff including HTTP 429/5xx, timeout, OAuth
token renewal and conservative token/request budgets. `--use-api` permits calls; only `--apply` writes accepted
results. Existing bindings are excluded and therefore never silently overwritten.

The prompt supplies bounded product data plus taxonomy values and meanings. API JSON-schema output
is used when supported, followed by backend validation and at most one repair. Invented labels are
never mapped to `other`. Category-only results are preserved but not automatically bound.
Automatic binding requires compatible material/work data and evidence. Reject, uncertain,
conflict, API failure, or category-only output remains for admin review. Model self-confidence is
not treated as probability.

ML is always evaluated first. Taxonomy-consistent results at or above 0.6 are accepted. Only
low-confidence renovation candidates, unknowns, and taxonomy conflicts are GigaChat-eligible;
non-renovation/furnishing products are not blanket-sent. Outages retain the ML/admin path. The
production script and notebook share this policy.

## Estimate explanations

When `RC_GIGACHAT_EXPLANATIONS=true`, estimate generation sends one bounded batch containing only
selected products, room/work context, product fields, calculated cost and the actual ranker signal
parts. Returned text can update `reason`; deterministic `why` remains present. The call cannot
change selection. Any API or validation failure only adds a warning, leaving estimate generation
functional. Responses are cached.

## Configuration

Set `RC_GIGACHAT_ENABLED=true` and `RC_GIGACHAT_CREDENTIALS` to the project's Base64 Authorization
Key (without the word `Basic`). Optional settings are documented in `.env.example`, including
scope, model, URLs, SSL verification, timeout, retries, cache path, token budget and explanation
toggle. The trusted classifier artifact has one canonical configurable default:
`ml_workspace/model/tfidf_logreg/model`.

Set `RC_GIGACHAT_CA_BUNDLE=certs/gigachat_ca_bundle.pem` (or another local PEM bundle). One verified
TLS context is used by OAuth, model discovery, classifications, retries, and explanations.
Verification remains enabled by default; `verify=False` is not an operational solution.

## Safe 10–30-product repeat pilot

1. Keep credentials and any private CA path only in ignored local environment configuration.
2. Configure the CA bundle, selected model, 30-request maximum, token budget, and conservative
   per-request reservation.
3. Execute the notebook offline first with both opt-ins false; confirm the fixed 240-row sample.
4. Enable both opt-ins only in the local session, run model discovery, and confirm JSON-schema
   compatibility. If the selected model rejects `response_format`, disable only that transport
   option and retain strict prompt/schema validation.
5. Start with 10 candidates. Inspect ledger attempts, reported/unknown usage, repairs, conflicts,
   latency, and concrete responses; expand to 30 only if the reserved budget allows it.
6. Do not use `--apply`. Complete the manual annotation template before claiming accuracy or
   precision; without labels, report paired agreement and coverage only.

The implementation follows the documented OAuth endpoint `/api/v2/oauth` (`Basic`, `RqUID`, scope,
expiring bearer token) and chat endpoint `/api/v1/chat/completions`. Official documentation was not
reachable from this environment (HTTP 403), so a credentialed small pilot should verify current
service response details before operational use.

## Remaining limitations

- `other_renovation_material` is intentionally not forced into a backend material.
- Electrical frames/terminals need explicit backend material slots if they should become estimate
  lines; until then they remain excluded from switch/cable candidates.
- Model scores are weak-label agreement scores, not calibrated probabilities.
- GigaChat output is also uncalibrated; schema validity is not correctness.
- Category-only output cannot create an estimate line without compatible material/work data.
- Structured-output support is model-dependent and must be confirmed in the bounded pilot.
- Provider-omitted usage remains unknown; conservative request/token reservations limit exposure.
- Historical keyword bindings remain untouched and can differ from the new prospective result.
- Run a representative GigaChat pilot and a real manual gold review before applying a large batch.
