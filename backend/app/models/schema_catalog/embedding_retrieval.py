"""Phase 3 (real semantic retrieval) — FAISS embedding-based table retrieval.

Design choices, and why:

- Table embeddings are precomputed ONCE per catalog (`ensure_table_embeddings`),
  and persisted into a FAISS index file on disk alongside the JSON catalog.
- We use faiss-cpu for blazing-fast vector similarity search without requiring
  a heavy vector DB (pgvector, Chroma, etc).
- The QUESTION embedding is computed at query time, synchronously.
"""
from __future__ import annotations

import os
import json
import asyncio
from typing import Optional

import httpx
import numpy as np
import faiss
from loguru import logger

from app.models.schema_catalog.models import SchemaCatalog
from app.models.schema_catalog.retrieval import _table_document
from app.models.schema_catalog.catalog_builder import CATALOG_DIR
from app.core.config.settings import settings


# --- Async Embedding clients ----------------------------------------------------

async def _embed_via_ollama_async(texts: list[str]) -> Optional[list[list[float]]]:
    base_url = settings.ollama_base_url.rstrip("/")
    vectors: list[Optional[list[float]]] = [None] * len(texts)
    
    async def fetch_embedding(idx: int, text: str, client: httpx.AsyncClient):
        try:
            resp = await client.post(
                f"{base_url}/api/embeddings",
                json={"model": settings.embedding_model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
            vectors[idx] = data.get("embedding")
        except Exception as e:
            logger.debug(f"Ollama embedding call failed: {e}")

    try:
        async with httpx.AsyncClient(timeout=settings.embedding_request_timeout_seconds) as client:
            # Batch in chunks of 50 to avoid overloading the local Ollama instance
            chunk_size = 50
            for i in range(0, len(texts), chunk_size):
                chunk = texts[i:i+chunk_size]
                tasks = [fetch_embedding(i + j, text, client) for j, text in enumerate(chunk)]
                await asyncio.gather(*tasks)
                
        if any(v is None for v in vectors):
            return None
        return vectors # type: ignore
    except Exception as e:
        logger.debug(f"Ollama batch embedding call failed: {e}")
        return None


async def _embed_via_openai_compatible_async(texts: list[str]) -> Optional[list[list[float]]]:
    base_url = (settings.embedding_base_url or "").rstrip("/")
    if not base_url:
        logger.debug("EMBEDDING_BASE_URL not set for openai_compatible embedding provider.")
        return None
        
    api_key = (settings.embedding_api_key or settings.openai_api_key or settings.openrouter_api_key or "").strip()
    if not api_key and "openai.com" in base_url:
        logger.error("No API key provided for OpenAI embeddings. Set EMBEDDING_API_KEY or OPENAI_API_KEY.")
        return None
        
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        vectors: list[Optional[list[float]]] = [None] * len(texts)
        semaphore = asyncio.Semaphore(4)  # Limit concurrent chunk requests to avoid overloading the API
        
        async def fetch_chunk(idx: int, chunk: list[str], client: httpx.AsyncClient):
            async with semaphore:
                for attempt in range(4):
                    try:
                        resp = await client.post(
                            f"{base_url}/embeddings",
                            headers=headers,
                            json={"model": settings.embedding_model, "input": chunk},
                        )
                        if resp.status_code == 429:
                            delay = 2.0 * (2 ** attempt) + 0.5
                            logger.warning(
                                f"Embedding API rate limited (429). Retrying chunk in {delay:.1f}s (attempt {attempt + 1}/4)..."
                            )
                            await asyncio.sleep(delay)
                            continue
                        resp.raise_for_status()
                        data = resp.json()
                        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
                        for i, item in enumerate(items):
                            vectors[idx + i] = item["embedding"]
                        return
                    except Exception as e:
                        if attempt < 3:
                            delay = 1.5 * (2 ** attempt)
                            logger.warning(
                                f"Embedding chunk call failed ({e}). Retrying in {delay:.1f}s (attempt {attempt + 1}/4)..."
                            )
                            await asyncio.sleep(delay)
                        else:
                            logger.warning(
                                f"OpenAI-compatible chunk embedding call permanently failed after retries: {e}"
                            )

        # Use a larger timeout for network embedding API
        async with httpx.AsyncClient(timeout=60.0) as client:
            chunk_size = 50
            tasks = []
            for i in range(0, len(texts), chunk_size):
                chunk = texts[i:i+chunk_size]
                tasks.append(fetch_chunk(i, chunk, client))
            await asyncio.gather(*tasks)
            
        if any(v is None for v in vectors):
            missing_count = sum(1 for v in vectors if v is None)
            logger.warning(f"Embedding generation incomplete: {missing_count}/{len(texts)} table vectors missing.")
            return None
        return vectors  # type: ignore
    except Exception as e:
        logger.warning(f"OpenAI-compatible embedding call failed: {e}")
        return None


async def _embed_texts_async(texts: list[str]) -> Optional[list[list[float]]]:
    if not texts:
        return []
    if settings.embedding_provider == "openai_compatible":
        return await _embed_via_openai_compatible_async(texts)
    return await _embed_via_ollama_async(texts)


# Sync version for the single question query (only safe to call outside running event loops)
def embed_question_sync(question: str) -> Optional[list[float]]:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    vectors = loop.run_until_complete(_embed_texts_async([question]))
    return vectors[0] if vectors else None

async def embed_question_async(question: str) -> Optional[list[float]]:
    vectors = await _embed_texts_async([question])
    return vectors[0] if vectors else None


# --- FAISS Disk Persistence ---------------------------------------------------

def _get_faiss_path(fingerprint: str) -> str:
    return str(CATALOG_DIR / f"{fingerprint}.faiss")

def _get_mapping_path(fingerprint: str) -> str:
    return str(CATALOG_DIR / f"{fingerprint}.faiss.json")


# --- Precomputing table embeddings (explicit, offline step) ---------------

async def ensure_table_embeddings(catalog: SchemaCatalog, force: bool = False) -> SchemaCatalog:
    if catalog.embeddings_built and catalog.embedding_model == settings.embedding_model and not force:
        return catalog

    table_names = list(catalog.tables.keys())
    documents = [_table_document(t, catalog) for t in table_names]
    
    logger.info(f"Generating embeddings for {len(table_names)} tables using {settings.embedding_provider}/{settings.embedding_model}...")
    vectors = await _embed_texts_async(documents)
    
    if vectors is None:
        logger.error(
            "\n" + "="*80 + "\n"
            "🚨 SEVERE WARNING: EMBEDDING GENERATION FAILED 🚨\n"
            f"Provider: {settings.embedding_provider}, Model: {settings.embedding_model}\n"
            "The system is falling back to TF-IDF / Exact Match for schema retrieval.\n"
            "This will MASSIVELY degrade query accuracy for large databases (>100 tables),\n"
            "especially for Arabic queries or synonymous column matching.\n"
            "Please fix your embedding configuration in .env!\n"
            + "="*80
        )
        return catalog

    # Build FAISS Index
    try:
        dimension = len(vectors[0])
        # Inner product is cosine similarity if vectors are L2 normalized
        # We L2-normalize vectors manually before adding to faiss.IndexFlatIP
        vectors_np = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(vectors_np)
        
        index = faiss.IndexFlatIP(dimension)
        index.add(vectors_np)
        
        faiss.write_index(index, _get_faiss_path(catalog.fingerprint))
        
        # Save mapping from index -> table_name
        with open(_get_mapping_path(catalog.fingerprint), "w", encoding="utf-8") as f:
            json.dump(table_names, f)

        # Store in-RAM cache immediately
        _FAISS_RAM_CACHE[catalog.fingerprint] = (index, table_names)

    except Exception as e:
        logger.error(f"Failed to build or save FAISS index: {e}")
        return catalog

    catalog.embeddings_built = True
    catalog.embedding_model = settings.embedding_model
    logger.info("Computed, cached in RAM, and saved FAISS index for %d tables.", len(table_names))
    return catalog


# --- Retrieval --------------------------------------------------------------

# In-RAM persistent FAISS cache: {fingerprint: (faiss.Index, table_mapping)}
_FAISS_RAM_CACHE: dict[str, tuple[Any, list[str]]] = {}


def clear_faiss_ram_cache(fingerprint: Optional[str] = None) -> None:
    """Clear in-RAM FAISS cache for a specific fingerprint or all."""
    if fingerprint:
        _FAISS_RAM_CACHE.pop(fingerprint, None)
    else:
        _FAISS_RAM_CACHE.clear()


class EmbeddingTableRetriever:
    """Ranks tables by cosine similarity using a persistent in-RAM FAISS index."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog
        self.index = None
        self.table_mapping = []

        if catalog.embeddings_built:
            fp = catalog.fingerprint
            if fp in _FAISS_RAM_CACHE:
                self.index, self.table_mapping = _FAISS_RAM_CACHE[fp]
            else:
                try:
                    faiss_path = _get_faiss_path(fp)
                    mapping_path = _get_mapping_path(fp)

                    if os.path.exists(faiss_path) and os.path.exists(mapping_path):
                        self.index = faiss.read_index(faiss_path)
                        with open(mapping_path, "r", encoding="utf-8") as f:
                            self.table_mapping = json.load(f)
                        _FAISS_RAM_CACHE[fp] = (self.index, self.table_mapping)
                except Exception as e:
                    logger.error(f"Failed to load FAISS index for {catalog.fingerprint}: {e}")

    def top_k(self, question: str, k: int = 12) -> list[str]:
        """Sync version of top_k (unsafe inside running event loops)"""
        if self.index is None or not self.table_mapping:
            return []
            
        q_vec = embed_question_sync(question)
        if q_vec is None:
            return []
            
        return self._search_faiss(q_vec, k)

    async def top_k_async(self, question: str, k: int = 12) -> list[str]:
        """Async version of top_k for use in web handlers."""
        if self.index is None or not self.table_mapping:
            return []
            
        q_vec = await embed_question_async(question)
        if q_vec is None:
            return []
            
        return self._search_faiss(q_vec, k)

    def _search_faiss(self, q_vec: list[float], k: int) -> list[str]:
        q_vec_np = np.array([q_vec], dtype=np.float32)
        faiss.normalize_L2(q_vec_np)
        
        # Search FAISS index
        search_k = min(k, len(self.table_mapping))
        distances, indices = self.index.search(q_vec_np, search_k)
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx != -1 and dist > 0.0:  # Valid index and positive similarity
                results.append(self.table_mapping[idx])
                
        return results
