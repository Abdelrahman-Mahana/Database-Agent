"""Feedback Learning Service (P2 Feature).

Ingests user corrections and annotations to dynamically enrich the SchemaCatalog
glossary and synonyms, improving future lexical and semantic retrieval.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from loguru import logger

from app.schema_catalog.models import SchemaCatalog
from app.schema_catalog.catalog_builder import CatalogBuilder


class FeedbackService:
    """Processes user corrections to continuously improve catalog metadata."""

    def __init__(self, catalog_builder: Optional[CatalogBuilder] = None):
        self.catalog_builder = catalog_builder or CatalogBuilder()

    def record_term_synonym(
        self,
        catalog: SchemaCatalog,
        target_entity: str,  # "table" or "column"
        target_name: str,    # "customers" or "orders.amount"
        synonym: str,
        user_id: Optional[str] = None,
    ) -> SchemaCatalog:
        """
        Add a user-provided synonym to a table or column in the catalog
        and persist the updated catalog to disk.
        """
        clean_synonym = synonym.strip().lower()
        if not clean_synonym:
            return catalog

        if target_entity == "table":
            tprof = catalog.tables.get(target_name)
            if tprof:
                if clean_synonym not in tprof.synonyms:
                    tprof.synonyms.append(clean_synonym)
                    tprof.synonyms.sort()
                    logger.info("Feedback learning: Added table synonym '%s' -> '%s'", clean_synonym, target_name)
        elif target_entity == "column" and "." in target_name:
            tname, cname = target_name.split(".", 1)
            tprof = catalog.tables.get(tname)
            if tprof:
                for col in tprof.columns:
                    if col.name == cname:
                        if clean_synonym not in col.synonyms:
                            col.synonyms.append(clean_synonym)
                            col.synonyms.sort()
                            logger.info("Feedback learning: Added column synonym '%s' -> '%s'", clean_synonym, target_name)
                        break

        # Invalidate in-RAM retriever caches on catalog
        try:
            catalog._cached_alias_index = None
            catalog._cached_tfidf_retriever = None
            catalog._synonym_index = None
        except Exception:
            pass

        # Persist updated catalog to disk
        self.catalog_builder._save_to_disk(catalog)
        return catalog

    def record_table_description(
        self,
        catalog: SchemaCatalog,
        table_name: str,
        description: str,
    ) -> SchemaCatalog:
        """Update table description from expert user annotation."""
        tprof = catalog.tables.get(table_name)
        if tprof and description.strip():
            tprof.description = description.strip()
            self.catalog_builder._save_to_disk(catalog)
            logger.info("Feedback learning: Updated description for table '%s'", table_name)
        return catalog

    def record_claim_feedback(
        self,
        claim_id: str,
        statement: str,
        user_rating: int,
        question: str = "",
        user_correction: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record user feedback or correction on a generated answer claim."""
        from app.database.system_store import system_store
        result = system_store.record_claim_feedback(
            claim_id=claim_id,
            statement=statement,
            user_rating=user_rating,
            question=question,
            user_correction=user_correction,
            user_id=user_id,
        )
        logger.info("Recorded feedback for claim '%s' (rating=%d)", claim_id, user_rating)
        return result

    def get_claim_feedback(
        self,
        claim_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve feedback history for claims."""
        from app.database.system_store import system_store
        return system_store.get_claim_feedback(claim_id=claim_id, limit=limit)


# Global singleton instance
feedback_service = FeedbackService()
