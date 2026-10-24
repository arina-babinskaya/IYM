from functools import lru_cache
from typing import Any

from app.schemas import ChecklistItem
from app.taxonomy import WorkType

UNPRICED_ROLES = {"tool", "consumable", "protective_equipment"}


@lru_cache
def _source() -> dict[str, list[dict[str, Any]]]:
    try:
        from ml_workspace.taxonomy.work_type_materials_v2 import WORK_TYPE_MATERIALS
    except ImportError:
        return {}
    return WORK_TYPE_MATERIALS


def checklist(work: WorkType, roles: set[str] | None = None) -> list[ChecklistItem]:
    items = sorted(_source().get(work.value, []), key=lambda i: -float(i.get("weight", 0)))
    return [ChecklistItem(item=i["item"], role=i["role"], note=i.get("note"))
            for i in items if roles is None or i["role"] in roles]
