"""Standalone explainable Top-K candidate ranker prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Candidate:
    product_id: int
    work_types: tuple[str, ...]
    material_roles: tuple[tuple[str, str], ...]
    room_types: tuple[str, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)
    applicability_score: float = 0.0
    quality_score: float | None = None
    quality_evidence: tuple[str, ...] = ()
    price: float | None = None
    in_stock: bool | None = None


@dataclass(frozen=True)
class RankedCandidate:
    product_id: int
    suitability_score: float
    price: float | None
    reasons: tuple[str, ...]
    missing_quality_data: bool


def rank_candidates(candidates: list[Candidate], work_type: str, material_role: str, room_type: str | None = None,
                    required_properties: dict[str, Any] | None = None, strategy: str = "quality",
                    max_price: float | None = None, top_k: int = 5) -> list[RankedCandidate]:
    """Apply hard compatibility filters, then stable suitability ranking.

    Price is only a budget constraint/tie-breaker. It never increases quality.
    """
    required_properties = required_properties or {}
    ranked = []
    for candidate in candidates:
        if work_type not in candidate.work_types or (work_type, material_role) not in candidate.material_roles:
            continue
        if candidate.in_stock is False:
            continue
        if room_type and candidate.room_types and room_type not in candidate.room_types:
            continue
        if any(candidate.properties.get(key) != value for key, value in required_properties.items()):
            continue
        if max_price is not None and candidate.price is not None and candidate.price > max_price:
            continue
        reasons = [f"work_type={work_type}", f"material_role={material_role}"]
        score = 0.65 * max(0.0, min(1.0, candidate.applicability_score))
        if room_type:
            if room_type in candidate.room_types:
                score += 0.20
                reasons.append(f"room={room_type}")
            elif not candidate.room_types:
                reasons.append("room_data_missing")
        missing_quality = candidate.quality_score is None
        if candidate.quality_score is not None:
            score += 0.15 * max(0.0, min(1.0, candidate.quality_score))
            reasons.extend(candidate.quality_evidence or ("quality_score_available",))
        else:
            reasons.append("quality_data_missing")
        ranked.append(RankedCandidate(candidate.product_id, round(score, 6), candidate.price,
                                      tuple(reasons), missing_quality))
    if strategy not in {"quality", "budget"}:
        raise ValueError("strategy must be quality or budget")
    if strategy == "budget":
        ranked.sort(key=lambda x: (-x.suitability_score, x.price is None, x.price if x.price is not None else float("inf"), x.product_id))
    else:
        ranked.sort(key=lambda x: (-x.suitability_score, x.missing_quality_data, x.product_id))
    return ranked[:top_k]
