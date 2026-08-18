"""Automatic database onboarding (Rebuild Plan — Phase 4).

Ties together three already-built, previously-manual/test-only steps into
one background job that runs once whenever the app connects to a database
it hasn't seen before:

  1. CatalogBuilder.get_or_build()      — structural profile (Phase 1)
  2. build_glossary() + merge_glossary() — LLM business glossary (Phase 1)
  3. CatalogBuilder.enrich_with_embeddings() — table embeddings (Phase 3,
     only if SCHEMA_RETRIEVAL_METHOD=embedding)

Design constraints (same rules the individual steps already followed):
  - Never blocks the user-facing /connect response — always scheduled as a
    FastAPI BackgroundTask, fire-and-forget from the request's perspective.
  - Never crashes anything — every step is best-effort; a failure at any
    stage just means the next question falls back to the layer below it
    (TF-IDF/FK-centrality instead of embeddings, raw column names instead of
    a glossary), exactly like every other fallback in this pipeline.
  - Idempotent / cheap to call repeatedly: each step already no-ops when its
    own persisted flag (`glossary_enriched`, `embeddings_built`) is already
    set for the current schema fingerprint, so re-connecting to the same
    database twice doesn't repeat LLM/embedding calls.
"""
from __future__ import annotations

from loguru import logger

from app.config.settings import settings
from app.services.sql_service import SchemaService
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.schema_catalog.glossary import build_glossary
from app.llm.model import get_llm_client


async def onboard_database(schema_service: SchemaService) -> None:
    """Run the full onboarding pipeline for whatever database `schema_service`
    is currently bound to. Safe to call on every /connect - each stage is a
    cheap no-op once already done for this schema's fingerprint."""
    if not settings.enable_auto_onboarding:
        return

    db_name = "?"
    try:
        db_name = schema_service.get_database_name()
        catalog_builder = CatalogBuilder(schema_service)
        catalog = catalog_builder.get_or_build()
        logger.info("Onboarding %s: structural profile ready (%d tables).", db_name, len(catalog.tables))

        # 1. Background profiling (row counts, values)
        await catalog_builder.build_async(catalog.fingerprint)
        catalog = catalog_builder.get_or_build()

        if not catalog.glossary_enriched:
            llm_client = get_llm_client()
            glossary = await build_glossary(catalog, llm_client)
            catalog = catalog_builder.merge_glossary(catalog, glossary)
            logger.info(
                "Onboarding %s: glossary built (%d table entries, %d column entries).",
                db_name, len(glossary.get("tables", {})), len(glossary.get("columns", {})),
            )
        else:
            logger.debug("Onboarding %s: glossary already built, skipping.", db_name)

        if settings.schema_retrieval_method == "embedding" and not catalog.embeddings_built:
            catalog = await catalog_builder.enrich_with_embeddings(catalog)
            if catalog.embeddings_built:
                logger.info("Onboarding %s: table embeddings computed.", db_name)
            else:
                logger.warning(
                    "Onboarding %s: embedding computation did not complete - "
                    "retrieval will keep using TF-IDF/FK-centrality.", db_name
                )
        elif catalog.embeddings_built:
            logger.debug("Onboarding %s: embeddings already computed, skipping.", db_name)

        # Warm DatabaseContext in RAM with all pre-built indexes (join graph, TF-IDF, glossary, inverted index)
        try:
            db_ctx = schema_service.get_database_context()
            db_ctx.catalog = catalog
            db_ctx.ensure_indexes(force=True)
            logger.info("Onboarding %s: RAM DatabaseContext pre-indexed and ready.", db_name)
        except Exception as e:
            logger.debug("Failed to warm DatabaseContext indexes: %s", e)

    except Exception as e:
        # Onboarding is pure enrichment. Any failure here must never surface
        # to the user or break question-answering - it just means the next
        # question runs with a thinner catalog (no glossary/embeddings yet)
        # and falls back exactly like it would have before this existed.
        logger.warning("Automatic onboarding failed for %s (non-fatal): %s", db_name, e)
