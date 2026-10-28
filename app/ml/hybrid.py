"""Shared production/notebook decision policy for optional GigaChat review."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.llm.gigachat import GigaClassification
from app.schemas import Suggestion
from app.taxonomy import Material


@dataclass(frozen=True)
class HybridDecision:
    action: Literal["accept_ml", "accept_gigachat", "admin_review"]
    level: Literal["estimate_ready", "category_only", "abstention"]
    reason: str


def eligible_for_gigachat(ml: Suggestion, threshold: float = .7) -> bool:
    """Review only uncertain renovation candidates or taxonomy conflicts, never all non-renovation goods."""
    flags = ml.flags
    if flags.get("domain_non_renovation") or flags.get("domain_furnishing"):
        return False
    relevant = flags.get("domain_renovation") or flags.get("ml_unknown") or flags.get("taxonomy_inconsistent")
    return bool(relevant and (ml.confidence < threshold or ml.material == Material.other
                              or flags.get("ml_unknown") or flags.get("taxonomy_inconsistent")))


def decide_hybrid(ml: Suggestion, giga: GigaClassification | None, threshold: float = .7) -> HybridDecision:
    if (ml.confidence >= threshold and ml.material != Material.other
            and not ml.flags.get("ml_unknown") and not ml.flags.get("taxonomy_inconsistent")):
        level = "estimate_ready" if ml.work_types else "category_only"
        return HybridDecision("accept_ml", level, "high-confidence taxonomy-consistent ML prediction")
    if giga is None:
        return HybridDecision("admin_review", "abstention", "GigaChat unavailable or not run")
    if giga.decision != "accept" or giga.validation_status != "valid":
        return HybridDecision("admin_review", "abstention", f"GigaChat {giga.decision}/{giga.validation_status}")
    if giga.result_level == "estimate_ready" and giga.evidence:
        return HybridDecision("accept_gigachat", "estimate_ready", "validated material/work binding with evidence")
    return HybridDecision("admin_review", "category_only", "valid broad category is not estimate-ready")


def gigachat_suggestion(result: GigaClassification, *, model: str, confidence: float = .8) -> Suggestion:
    """Convert only a safely publishable estimate-ready result into a persisted binding."""
    if (result.decision != "accept" or result.validation_status != "valid"
            or result.result_level != "estimate_ready" or result.product_category is None
            or result.material is None or not result.work_types or not result.evidence):
        raise ValueError("GigaChat result is not safe for estimate binding")
    return Suggestion(product_category=result.product_category, material=result.material,
        work_types=result.work_types, confidence=confidence,
        flags={"gigachat_validated": True}, model=f"gigachat:{model}")
