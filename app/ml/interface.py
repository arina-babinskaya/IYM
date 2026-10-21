from typing import Protocol

from app.models import Product, ProductBinding
from app.schemas import RoomInput, Suggestion


class ProductClassifier(Protocol):
    name: str

    def predict(self, products: list[Product]) -> list[Suggestion]:
        ...


class Ranker(Protocol):
    def rank(self, candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> list[Product]:
        ...
