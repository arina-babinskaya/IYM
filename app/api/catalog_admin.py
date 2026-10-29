from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_catalog_matching_classifier
from app.catalog.matching_repository import CatalogAssignmentStatus, CatalogMatchingRepo
from app.catalog.repository import MANUAL_ID_START, CatalogRepo, to_brief
from app.db import get_session, get_sessionmaker
from app.models import Product
from app.schemas import (
    CatalogAdminRow,
    CatalogAdminStats,
    CatalogAssignmentOut,
    CatalogCategorizationJob,
    CatalogCategoryIn,
    CatalogMatchAlternative,
    CatalogTaxonomyCategory,
    CatalogTaxonomyOut,
    ProductCreate,
)
from ml_workspace.catalog_matching.taxonomy.catalog_taxonomy import (
    CATEGORY_BY_ID,
    PARENT_NAMES,
    TAXONOMY_VERSION,
)

router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog-matching"])
logger = logging.getLogger(__name__)

_catalog_task: asyncio.Task[None] | None = None
_catalog_job: CatalogCategorizationJob | None = None
_catalog_started: dict[str, float] = {}


def get_catalog_repo(session: Session = Depends(get_session)) -> CatalogMatchingRepo:
    return CatalogMatchingRepo(session)


def _assignment_out(item) -> CatalogAssignmentOut:
    category = CATEGORY_BY_ID[item.category_id]
    return CatalogAssignmentOut(
        category_id=item.category_id,
        category_name=category.name,
        score=item.model_score,
        top_3=[CatalogMatchAlternative.model_validate(value) for value in (item.alternatives or [])],
        model=item.model_version,
        taxonomy_version=item.taxonomy_version,
        status=item.status,
        source=item.source,
    )


@router.get("/taxonomy", response_model=CatalogTaxonomyOut)
def catalog_taxonomy() -> CatalogTaxonomyOut:
    # review.unresolved is a review sentinel, not one of the model's 90 trainable leaves.
    categories = [item for item in CATEGORY_BY_ID.values() if item.id != "review.unresolved"]
    return CatalogTaxonomyOut(
        version=TAXONOMY_VERSION,
        category_count=len(categories),
        categories=[
            CatalogTaxonomyCategory(
                id=item.id, name=item.name, parent_id=item.parent_id,
                parent_name=PARENT_NAMES[item.parent_id], definition=item.definition,
            )
            for item in categories
        ],
    )


@router.get("/stats", response_model=CatalogAdminStats)
def catalog_stats(repo: CatalogMatchingRepo = Depends(get_catalog_repo)) -> CatalogAdminStats:
    return CatalogAdminStats.model_validate(repo.stats())


@router.get("/products", response_model=list[CatalogAdminRow])
def catalog_products(
    assignment_status: CatalogAssignmentStatus = "all",
    category_id: str | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: CatalogMatchingRepo = Depends(get_catalog_repo),
) -> list[CatalogAdminRow]:
    if category_id is not None and category_id not in CATEGORY_BY_ID:
        raise HTTPException(422, "unknown catalog category")
    return [
        CatalogAdminRow(
            product=to_brief(product),
            source_category=next(iter(reversed(list((product.categories or {}).values()))), None),
            manual=product.id >= MANUAL_ID_START,
            assignment=_assignment_out(assignment) if assignment else None,
        )
        for product, assignment in repo.list_rows(assignment_status, category_id, q, limit, offset)
    ]


@router.post("/products", response_model=CatalogAdminRow, status_code=201)
def create_catalog_product(
    data: ProductCreate,
    repo: CatalogMatchingRepo = Depends(get_catalog_repo),
) -> CatalogAdminRow:
    product = CatalogRepo(repo.session).create_manual(data)
    return CatalogAdminRow(
        product=to_brief(product),
        source_category=next(iter(reversed(list((product.categories or {}).values()))), None),
        manual=True,
        assignment=None,
    )


@router.put("/products/{product_id}/category", response_model=CatalogAssignmentOut)
def save_catalog_category(
    product_id: int,
    data: CatalogCategoryIn,
    repo: CatalogMatchingRepo = Depends(get_catalog_repo),
) -> CatalogAssignmentOut:
    if data.category_id not in CATEGORY_BY_ID or data.category_id == "review.unresolved":
        raise HTTPException(422, "unknown or non-trainable catalog category")
    if repo.session.get(Product, product_id) is None:
        raise HTTPException(404, "товар не найден")
    return _assignment_out(repo.save_manual(product_id, data.category_id, TAXONOMY_VERSION))


async def _predict_resilient(classifier, products):
    valid = [product for product in products if isinstance(product.name, str) and product.name.strip()]
    invalid = len(products) - len(valid)
    if not valid:
        return [], invalid
    try:
        return await asyncio.to_thread(classifier.predict_batch, valid, 3), invalid
    except Exception as batch_error:
        logger.warning("catalog batch inference failed; isolating products: %s", batch_error)
        results = []
        errors = invalid
        for product in valid:
            try:
                results.append(await asyncio.to_thread(classifier.predict_one, product, 3))
            except Exception as exc:
                errors += 1
                logger.warning("catalog inference failed product_id=%s: %s", product.id, exc)
        return results, errors


async def _run_catalog_job(job: CatalogCategorizationJob, batch: int) -> None:
    global _catalog_task
    try:
        classifier = None
        with get_sessionmaker()() as session:
            repo = CatalogMatchingRepo(session)
            initial_stats = repo.stats()
            job.total = int(initial_stats["products_total"])
            # Existing valid assignments are examined by the indexed coverage query and retained;
            # inference is necessary only for products without a catalog assignment.
            job.processed = int(initial_stats["assigned"])
            job.unchanged = int(initial_stats["assigned"])
            job.manual_preserved = int(initial_stats["manual_confirmed"])
            job.needs_review = int(initial_stats["needs_review"])
            after_id = -1
            while products := repo.unassigned_products_batch(batch, after_id):
                if classifier is None:
                    classifier = get_catalog_matching_classifier()
                after_id = products[-1].id
                job.phase = "classifying"
                inference_started = time.perf_counter()
                results, errors = await _predict_resilient(classifier, products)
                job.inference_ms += int((time.perf_counter() - inference_started) * 1000)
                job.phase = "saving"
                persistence_started = time.perf_counter()
                counts = repo.save_predictions(results)
                job.persistence_ms += int((time.perf_counter() - persistence_started) * 1000)
                job.processed += len(products)
                job.categorized += len(results)
                job.inserted += counts.inserted
                job.updated += counts.updated
                job.unchanged += counts.unchanged
                job.manual_preserved += counts.manual_preserved
                job.needs_review += counts.needs_review
                job.errors += errors
                job.batches += 1
                job.elapsed_ms = int((time.perf_counter() - _catalog_started[job.id]) * 1000)
                logger.info(
                    "catalog categorization batch=%s processed=%s inserted=%s updated=%s unchanged=%s "
                    "manual_preserved=%s review=%s errors=%s",
                    job.batches, len(products), counts.inserted, counts.updated, counts.unchanged,
                    counts.manual_preserved, counts.needs_review, errors,
                )
            job.stats = CatalogAdminStats.model_validate(repo.stats())
        job.status, job.phase = "completed", "completed"
    except asyncio.CancelledError:
        job.status, job.phase, job.error = "cancelled", "cancelled", "catalog categorization was cancelled"
        raise
    except Exception as exc:
        logger.exception("catalog categorization job %s failed", job.id)
        job.status, job.phase, job.error = "failed", "failed", f"{type(exc).__name__}: {exc}"
    finally:
        job.elapsed_ms = int((time.perf_counter() - _catalog_started[job.id]) * 1000)
        _catalog_task = None


@router.post("/categorize", response_model=CatalogCategorizationJob, status_code=202)
async def start_catalog_categorization(
    response: Response,
    batch: int = Query(1000, ge=1, le=5000),
) -> CatalogCategorizationJob:
    global _catalog_job, _catalog_task
    if _catalog_task is not None and not _catalog_task.done():
        response.status_code = status.HTTP_202_ACCEPTED
        return _catalog_job
    job = CatalogCategorizationJob(id=str(uuid.uuid4()), status="running", phase="starting")
    _catalog_job = job
    _catalog_started[job.id] = time.perf_counter()
    _catalog_task = asyncio.create_task(_run_catalog_job(job, batch))
    return job


@router.get("/categorize/status", response_model=CatalogCategorizationJob)
def catalog_categorization_status() -> CatalogCategorizationJob:
    if _catalog_job is None:
        raise HTTPException(404, "catalog categorization has not been started")
    if _catalog_job.status == "running":
        _catalog_job.elapsed_ms = int((time.perf_counter() - _catalog_started[_catalog_job.id]) * 1000)
    return _catalog_job
