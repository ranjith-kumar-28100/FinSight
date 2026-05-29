"""In-memory hybrid retrieval over the user's transactions.

Backed by Qdrant in-memory mode:
  - Dense vectors: Azure ``text-embedding-3-small`` (1536-d cosine).
  - Sparse vectors: FastEmbed's ``Qdrant/bm25`` lexical model.

Hybrid retrieval uses Qdrant's Query API with Reciprocal Rank Fusion (RRF)
to combine dense and sparse rankings into one ordered list.

The collection is rebuilt from scratch on every call to ``index_all`` —
cheap enough for a few thousand transactions and keeps the data model simple.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from qdrant_client import QdrantClient, models

from backend.llm.provider import LLMProvider
from backend.models.transaction import Transaction, TransactionDirection, TransactionSource

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_DIMS = 1536
COLLECTION_NAME = "finsight_transactions"
DEFAULT_BM25_MODEL = "Qdrant/bm25"


@dataclass
class RetrievedTransaction:
    """A single transaction returned from a hybrid search."""

    txn_id: str
    score: float
    date: date
    amount: Decimal
    direction: str
    source: str
    merchant: str
    category: str
    description: str

    def to_dict(self) -> dict:
        return {
            "txn_id": self.txn_id,
            "score": round(self.score, 4),
            "date": self.date.isoformat(),
            "amount": str(self.amount),
            "direction": self.direction,
            "source": self.source,
            "merchant": self.merchant,
            "category": self.category,
            "description": self.description,
        }


class TransactionRAGStore:
    """Build and query a hybrid Qdrant index over Transaction rows."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._client = QdrantClient(":memory:")
        self._sparse_model = None  # lazy
        self._size = 0
        self._dense_enabled = True

    # ------------------------------------------------------------------
    # Sparse model (lazy — onnxruntime can take a moment to warm up)
    # ------------------------------------------------------------------
    def _get_sparse_model(self):
        if self._sparse_model is None:
            from fastembed import SparseTextEmbedding
            self._sparse_model = SparseTextEmbedding(DEFAULT_BM25_MODEL)
        return self._sparse_model

    # ------------------------------------------------------------------
    # Index build
    # ------------------------------------------------------------------
    def index_all(self, transactions: Iterable[Transaction]) -> int:
        """(Re)build the collection from scratch with the given transactions.

        Returns the number of points written. Both bank rows and orphan wallet
        rows can be passed; the source field is preserved on each point so the
        caller can filter at query time.
        """
        txns = [t for t in transactions if t.raw_description]
        if not txns:
            self._size = 0
            return 0

        self._recreate_collection()
        texts = [_compose_text(t) for t in txns]

        try:
            dense_vecs = self._llm.embed_batch(texts)
            if len(dense_vecs) != len(texts):
                raise RuntimeError(
                    f"embedding count mismatch: got {len(dense_vecs)}, expected {len(texts)}"
                )
            self._dense_enabled = True
        except Exception as e:
            logger.warning(
                "Dense embedding failed (%s) — falling back to sparse-only retrieval.",
                e,
            )
            dense_vecs = [[0.0] * DENSE_DIMS for _ in texts]
            self._dense_enabled = False

        sparse_model = self._get_sparse_model()
        sparse_vecs = list(sparse_model.embed(texts))

        points: list[models.PointStruct] = []
        for txn, text, dense, sparse in zip(txns, texts, dense_vecs, sparse_vecs):
            sparse_vec = models.SparseVector(
                indices=sparse.indices.tolist(),
                values=sparse.values.tolist(),
            )
            vector_payload: dict = {SPARSE_VECTOR_NAME: sparse_vec}
            if self._dense_enabled:
                vector_payload[DENSE_VECTOR_NAME] = dense
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector_payload,
                    payload={
                        "txn_id": txn.txn_id,
                        "date": txn.date.isoformat(),
                        "amount": str(txn.amount),
                        "direction": txn.direction.value,
                        "source": txn.source.value,
                        "merchant": _merchant(txn),
                        "category": txn.category or "",
                        "description": txn.raw_description,
                        "text": text,
                    },
                )
            )

        # Upsert in chunks so very large indexes don't blow memory.
        CHUNK = 256
        for start in range(0, len(points), CHUNK):
            self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[start: start + CHUNK],
            )
        self._size = len(points)
        logger.info(
            "RAG index built: %d points (dense=%s, sparse=bm25).",
            self._size, self._dense_enabled,
        )
        return self._size

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def hybrid_search(
        self,
        query: str,
        k: int = 10,
        source: Optional[str] = None,
        direction: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[RetrievedTransaction]:
        """Hybrid retrieve top-k transactions for a natural-language query.

        Combines dense (semantic) and sparse (BM25) rankings via RRF.
        Optional filters narrow the candidate set before fusion.
        """
        if self._size == 0:
            return []

        query = query.strip()
        if not query:
            return []

        # Optional metadata filter
        must: list[models.FieldCondition] = []
        if source:
            must.append(models.FieldCondition(
                key="source", match=models.MatchValue(value=source)))
        if direction:
            must.append(models.FieldCondition(key="direction",
                        match=models.MatchValue(value=direction)))
        if category:
            must.append(models.FieldCondition(key="category",
                        match=models.MatchValue(value=category)))
        if start_date or end_date:
            must.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=start_date.isoformat() if start_date else None,
                        lte=end_date.isoformat() if end_date else None,
                    ),
                )
            )
        qfilter = models.Filter(must=must) if must else None

        # Sparse always available; dense if embeddings succeeded.
        sparse_model = self._get_sparse_model()
        sparse_q = next(iter(sparse_model.query_embed([query])))
        sparse_query = models.SparseVector(
            indices=sparse_q.indices.tolist(),
            values=sparse_q.values.tolist(),
        )

        prefetch: list[models.Prefetch] = [
            models.Prefetch(
                query=sparse_query,
                using=SPARSE_VECTOR_NAME,
                limit=max(k * 4, 20),
                filter=qfilter,
            )
        ]
        if self._dense_enabled:
            try:
                dense_vec = self._llm.embed_batch([query])[0]
                prefetch.append(
                    models.Prefetch(
                        query=dense_vec,
                        using=DENSE_VECTOR_NAME,
                        limit=max(k * 4, 20),
                        filter=qfilter,
                    )
                )
            except Exception as e:
                logger.warning(
                    "Query embedding failed (%s) — sparse-only this query.", e)

        result = self._client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )

        out: list[RetrievedTransaction] = []
        for point in result.points:
            p = point.payload or {}
            out.append(
                RetrievedTransaction(
                    txn_id=p.get("txn_id", ""),
                    score=float(point.score or 0.0),
                    date=date.fromisoformat(p["date"]),
                    amount=Decimal(p.get("amount", "0")),
                    direction=p.get("direction", ""),
                    source=p.get("source", ""),
                    merchant=p.get("merchant", ""),
                    category=p.get("category", ""),
                    description=p.get("description", ""),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def size(self) -> int:
        return self._size

    @property
    def dense_enabled(self) -> bool:
        return self._dense_enabled

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _recreate_collection(self) -> None:
        if self._client.collection_exists(COLLECTION_NAME):
            self._client.delete_collection(COLLECTION_NAME)
        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=DENSE_DIMS, distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _merchant(txn: Transaction) -> str:
    return txn.enriched_counterparty or txn.counterparty or ""


def _compose_text(txn: Transaction) -> str:
    """Build the searchable text representation of a transaction."""
    parts = [
        _merchant(txn) or "",
        txn.category or "",
        txn.subcategory or "",
        txn.raw_description or "",
        f"₹{txn.amount}",
        txn.direction.value,
        txn.date.strftime("%B %Y"),
    ]
    return " | ".join(p for p in parts if p)
