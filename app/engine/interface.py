from typing import Protocol

from app.catalog.repository import CatalogRepo
from app.ml.interface import Ranker
from app.models import Product
from app.schemas import EstimateRequest, EstimateResponse, ProductCalcRequest, ProductCalcResponse


class EstimateEngine(Protocol):
    def __init__(self, ranker: Ranker) -> None: ...

    def estimate(self, req: EstimateRequest, repo: CatalogRepo) -> EstimateResponse:
        ...

    def calc_product(self, product: Product, req: ProductCalcRequest, repo: CatalogRepo) -> ProductCalcResponse:
        ...

    async def explain(self, req: EstimateRequest, resp: EstimateResponse) -> EstimateResponse:
        ...


class CalcError(ValueError):
    pass
