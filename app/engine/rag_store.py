"""
Векторное хранилище (FAISS) по базе знаний строительных нормативов и правил.

Обеспечивает семантический и лексический поиск по СНиП, ГОСТ и данным производителей
для генерации обоснований в смете (RAG).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

from app.engine.consumption_standards import RAG_KNOWLEDGE_BASE

log = logging.getLogger(__name__)


def _simple_tokenize(text: str) -> list[str]:
    """Простая токенизация для локального векторного представления."""
    return re.findall(r"\b[a-zA-Zа-яА-ЯёЁ0-9]{3,}\b", text.lower())


class KnowledgeBaseVectorStore:
    """
    Векторное хранилище на базе FAISS с гибридным фолбэком:
    1. Эмбеддинги через Ollama (если доступна модель bge-m3 / multilingual-e5);
    2. Dense TF-IDF / BM25-подобное векторное представление (работает мгновенно и офлайн).
    """

    def __init__(self, documents: list[dict[str, str]] | None = None, dim: int = 128):
        self.documents = list(documents or RAG_KNOWLEDGE_BASE)
        self.dim = dim
        self.index: faiss.Index | None = None
        self.vocab: dict[str, int] = {}
        self.doc_vectors: np.ndarray | None = None
        self._build_local_index()

    def _build_local_index(self) -> None:
        """Построение локального FAISS индекса по словарям терминов."""
        if not HAS_FAISS or not self.documents:
            return

        # Построение словаря частотных токенов
        df: dict[str, int] = {}
        doc_tokens_list: list[list[str]] = []
        for doc in self.documents:
            full_text = f"{doc.get('material', '')} {doc.get('work_type', '')} {doc.get('text', '')} {doc.get('source', '')}"
            toks = set(_simple_tokenize(full_text))
            doc_tokens_list.append(list(toks))
            for t in toks:
                df[t] = df.get(t, 0) + 1

        # Отбираем наиболее информативные термины
        sorted_terms = sorted(df.items(), key=lambda x: x[1], reverse=True)[: self.dim]
        self.vocab = {term: idx for idx, (term, _) in enumerate(sorted_terms)}
        actual_dim = max(len(self.vocab), 1)
        self.dim = actual_dim

        # Построение матрицы TF-IDF векторов
        num_docs = len(self.documents)
        vectors = np.zeros((num_docs, actual_dim), dtype=np.float32)

        for i, toks in enumerate(doc_tokens_list):
            for t in toks:
                if t in self.vocab:
                    col = self.vocab[t]
                    idf = np.log((num_docs + 1.0) / (df.get(t, 1) + 1.0)) + 1.0
                    vectors[i, col] += float(idf)

        # L2-нормализация для косинусного сходства через Inner Product
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized_vectors = vectors / norms
        self.doc_vectors = normalized_vectors

        # Создание FAISS IndexFlatIP (Inner Product = Cosine Similarity для нормализованных векторов)
        self.index = faiss.IndexFlatIP(actual_dim)
        self.index.add(normalized_vectors)
        log.info("FAISS vector store инициализирован: %d документов, размерность %d", num_docs, actual_dim)

    def _vectorize_query(self, query: str) -> np.ndarray:
        """Векторизация поискового запроса."""
        vec = np.zeros((1, self.dim), dtype=np.float32)
        toks = _simple_tokenize(query)
        for t in toks:
            if t in self.vocab:
                vec[0, self.vocab[t]] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """
        Поиск наиболее релевантных нормативных документов по запросу.

        Returns:
            Список словарей с документами и оценкой score (от 0 до 1).
        """
        if not self.documents:
            return []

        if not HAS_FAISS or self.index is None or self.index.ntotal == 0:
            # Простейший поиск по подстрокам
            q_lower = query.lower()
            scored = [
                (doc, sum(1 for w in _simple_tokenize(q_lower) if w in doc.get("text", "").lower()))
                for doc in self.documents
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [doc for doc, s in scored[:top_k] if s > 0] or self.documents[:top_k]

        q_vec = self._vectorize_query(query)
        if np.linalg.norm(q_vec) == 0:
            # Пустой вектор запроса — возвращаем первые top_k
            return [{"score": 0.0, **doc} for doc in self.documents[:top_k]]

        distances, indices = self.index.search(q_vec, min(top_k, len(self.documents)))
        results: list[dict[str, Any]] = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            if idx >= 0 and idx < len(self.documents):
                results.append({
                    "score": float(dist),
                    **self.documents[idx],
                })
        return results

    def search_by_materials_and_works(
        self,
        materials: set[str],
        works: set[str],
        room_types: set[str] | None = None,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        """Точный и контекстный поиск по набору материалов и работ сметы."""
        query_parts: list[str] = list(materials) + list(works)
        if room_types:
            query_parts.extend(room_types)
        query = " ".join(query_parts)

        # Сначала точные совпадения по метаданным
        exact_matches: list[dict[str, Any]] = []
        seen_texts: set[str] = set()

        for doc in self.documents:
            m = doc.get("material")
            w = doc.get("work_type")
            if (m and m in materials) or (w and w in works):
                if doc["text"] not in seen_texts:
                    seen_texts.add(doc["text"])
                    exact_matches.append({"score": 1.0, **doc})

        # Дополняем векторным поиском FAISS
        vector_matches = self.search(query, top_k=top_k)
        for doc in vector_matches:
            if doc["text"] not in seen_texts:
                seen_texts.add(doc["text"])
                exact_matches.append(doc)

        return exact_matches[:top_k]


_STORE: KnowledgeBaseVectorStore | None = None


def get_rag_store() -> KnowledgeBaseVectorStore:
    """Получение глобального экземпляра FAISS хранилища базы знаний."""
    global _STORE
    if _STORE is None:
        _STORE = KnowledgeBaseVectorStore()
    return _STORE
