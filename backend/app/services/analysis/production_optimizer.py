"""Production Optimization & Resource Efficiency Engine (Phase 9).

Provides:
1. InvestigationCache: Caching of multi-query plans and verified evidence with freshness and database/schema isolation.
2. SemanticQueryCache: Configurable semantic similarity cache with zero cross-database contamination.
3. ModelRouter: Intelligent classification between deterministic execution, cheap models, and heavy reasoning models.
4. QueryDeduplicator: Semantic and deterministic deduplication of redundant QueryTasks.
5. SelfConsistencyGate: Conditional activation of multi-candidate SQL generation based on complexity, risk, and confidence.
6. SystemMetricsTracker: Baseline telemetry and real-time observability across latency, tokens, cost, cache hits, and query counts.
"""
from dataclasses import dataclass, field
import hashlib
import json
import logging
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from cachetools import TTLCache
from app.services.analysis.investigation_models import (
    EvidenceItem,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)
from app.core.config.settings import settings
from app.utils.text_processor import normalize_question

logger = logging.getLogger(__name__)


# ─── Model Tier Classification ───

class ModelTier(str, Enum):
    DETERMINISTIC = "deterministic"
    CHEAP_FAST = "cheap_fast"
    HEAVY_REASONING = "heavy_reasoning"


@dataclass
class ModelRouteDecision:
    tier: ModelTier
    model_name: str
    is_deterministic: bool
    estimated_cost_per_1k_tokens: float
    rationale: str


class ModelRouter:
    """Classifies tasks to run deterministically in Python/SQL or select appropriate model tiers."""

    @classmethod
    def route_task(
        cls,
        operation: str,
        complexity_score: float = 0.0,
        has_ambiguity: bool = False,
    ) -> ModelRouteDecision:
        """Route analytical or generation tasks to the most cost-effective tier."""
        op_lower = operation.lower()

        # 1. Deterministic operations: 0 tokens, 0ms latency
        deterministic_ops = {
            "statistics", "validation", "reconciliation", "coverage",
            "confidence", "ranking", "contribution_analysis", "formatting",
            "data_quality_check", "progress_evaluation",
        }
        if any(d in op_lower for d in deterministic_ops):
            return ModelRouteDecision(
                tier=ModelTier.DETERMINISTIC,
                model_name="deterministic_code",
                is_deterministic=True,
                estimated_cost_per_1k_tokens=0.0,
                rationale="Pure Python/pandas calculation without LLM overhead.",
            )

        # 2. Heavy Reasoning operations: complex SQL, ambiguous prompts, deep root cause
        if complexity_score > 0.7 or has_ambiguity or "root_cause_reasoning" in op_lower:
            return ModelRouteDecision(
                tier=ModelTier.HEAVY_REASONING,
                model_name=getattr(settings, "heavy_reasoning_model", "gpt-4o"),
                is_deterministic=False,
                estimated_cost_per_1k_tokens=0.005,
                rationale="High complexity/ambiguity task requiring advanced reasoning.",
            )

        # 3. Cheap & Fast operations: simple SQL, query understanding, translation
        return ModelRouteDecision(
            tier=ModelTier.CHEAP_FAST,
            model_name=getattr(settings, "fast_model", "gpt-4o-mini"),
            is_deterministic=False,
            estimated_cost_per_1k_tokens=0.0003,
            rationale="Standard routine query generation using cost-effective fast model.",
        )


# ─── Query Deduplication ───

class QueryDeduplicator:
    """Prevents executing duplicate or redundant QueryTasks when equivalent evidence is already available."""

    @staticmethod
    def is_task_redundant(
        task: QueryTask,
        state: InvestigationState,
    ) -> Tuple[bool, Optional[str]]:
        """Check if task is already covered by existing evidence or completed queries."""
        norm_sub = normalize_question(task.sub_question or task.purpose)

        # 1. Check completed queries
        for completed in state.completed_queries:
            if completed.status in (QueryExecutionStatus.SUCCESS, QueryExecutionStatus.CACHED):
                completed_norm = normalize_question(completed.sub_question or completed.purpose)
                if norm_sub == completed_norm and len(completed.rows) > 0:
                    return True, f"Identical query already executed ({completed.query_id})."

        # 2. Check accumulated evidence
        if task.required_metrics:
            req_set = {m.lower() for m in task.required_metrics}
            matching_ev = [
                ev for ev in state.evidence
                if ev.metric and ev.metric.lower() in req_set and ev.verified
            ]
            if len(matching_ev) == len(req_set) and len(matching_ev) > 0:
                return True, f"All required metrics {list(req_set)} already present in verified evidence."

        return False, None


# ─── Investigation Cache with Schema & Database Isolation ───

class InvestigationCache:
    """Caches analytical plans and verified evidence with database, schema, and freshness isolation."""

    def __init__(self, maxsize: int = 1000, default_ttl_seconds: int = 3600):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=default_ttl_seconds)

    def _build_key(
        self,
        question: str,
        database_fingerprint: str,
        schema_version: str,
        data_version: str = "",
    ) -> str:
        norm_q = normalize_question(question)
        raw = f"inv:{database_fingerprint}:{schema_version}:{data_version}:{norm_q}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(
        self,
        question: str,
        database_fingerprint: str,
        schema_version: str,
        data_version: str = "",
        max_age_seconds: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached investigation results if valid and fresh."""
        key = self._build_key(question, database_fingerprint, schema_version, data_version)
        entry = self._cache.get(key)
        if not entry:
            return None

        # Freshness validation
        if max_age_seconds is not None:
            cached_at = entry.get("timestamp", 0)
            if time.time() - cached_at > max_age_seconds:
                self._cache.pop(key, None)
                return None

        logger.info("Investigation cache HIT for question: '%s'", question)
        return entry.get("data")

    def set(
        self,
        question: str,
        database_fingerprint: str,
        schema_version: str,
        state: InvestigationState,
        data_version: str = "",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Cache investigation state, plan, and verified evidence."""
        key = self._build_key(question, database_fingerprint, schema_version, data_version)
        serialized_state = {
            "question": question,
            "evidence": [e.model_dump() for e in state.evidence if e.verified],
            "known_facts": list(state.known_facts),
            "completeness_score": state.completeness_score,
            "confidence_score": state.confidence_score,
            "status": state.status.value,
        }
        self._cache[key] = {
            "timestamp": time.time(),
            "data": serialized_state,
        }
        logger.info("Saved investigation state to cache for key: %s", key[:12])

    def clear(self) -> None:
        """Clear all cached investigations."""
        self._cache.clear()


# Global Singleton Investigation Cache
investigation_cache = InvestigationCache()


# ─── Semantic Cache with Strict Isolation ───

class SemanticQueryCache:
    """Configurable semantic cache for planning and questions with strict isolation."""

    def __init__(
        self,
        similarity_threshold: float = 0.92,
        maxsize: int = 2000,
        ttl_seconds: int = 1800,
    ):
        self.similarity_threshold = similarity_threshold
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    def _get_signature(self, text: str) -> Set[str]:
        words = set(re.findall(r"[a-zA-Z0-9_\u0600-\u06FF]+", text.lower()))
        return words

    def _jaccard_similarity(self, sig1: Set[str], sig2: Set[str]) -> float:
        if not sig1 or not sig2:
            return 0.0
        intersection = len(sig1.intersection(sig2))
        union = len(sig1.union(sig2))
        return intersection / union if union > 0 else 0.0

    def lookup(
        self,
        question: str,
        database_fingerprint: str,
        schema_version: str,
    ) -> Optional[Tuple[str, Any, float]]:
        """Search for semantically equivalent cached entries within the same database and schema version."""
        q_sig = self._get_signature(question)
        best_match = None
        best_score = 0.0

        for key, entry in self._cache.items():
            # Check database and schema isolation
            if entry["db"] != database_fingerprint or entry["schema_version"] != schema_version:
                continue

            sim = self._jaccard_similarity(q_sig, entry["sig"])
            if sim >= self.similarity_threshold and sim > best_score:
                best_score = sim
                best_match = (entry["question"], entry["result"], sim)

        if best_match:
            logger.info("Semantic cache HIT (score=%.2f) for question: '%s'", best_score, question)
            return best_match
        return None

    def store(
        self,
        question: str,
        database_fingerprint: str,
        schema_version: str,
        result: Any,
    ) -> None:
        """Store result with database and schema metadata."""
        key = f"{database_fingerprint}:{schema_version}:{hashlib.md5(question.encode('utf-8')).hexdigest()}"
        self._cache[key] = {
            "question": question,
            "sig": self._get_signature(question),
            "db": database_fingerprint,
            "schema_version": schema_version,
            "result": result,
            "timestamp": time.time(),
        }

    def clear(self) -> None:
        self._cache.clear()


# Global Singleton Semantic Cache
semantic_query_cache = SemanticQueryCache()


# ─── Conditional Self-Consistency Gate ───

class SelfConsistencyGate:
    """Decides conditionally whether to trigger multi-candidate SQL generation."""

    @staticmethod
    def should_trigger(
        question: str,
        table_count: int = 1,
        join_count: int = 0,
        ambiguity_score: float = 0.0,
        previous_failed: bool = False,
        confidence: float = 1.0,
    ) -> Tuple[bool, str]:
        """Determine if multi-candidate SQL generation is justified."""
        if previous_failed:
            return True, "Triggered self-consistency due to previous query execution failure."
        if confidence < 0.65:
            return True, f"Triggered self-consistency due to low confidence ({confidence:.2f})."
        if ambiguity_score > 0.50:
            return True, f"Triggered self-consistency due to high ambiguity score ({ambiguity_score:.2f})."
        if join_count >= 3 or table_count >= 4:
            return True, f"Triggered self-consistency due to query structural complexity ({join_count} joins)."

        return False, "Single fast-path candidate SQL generation used."


# ─── Production Observability & Telemetry ───

@dataclass
class TelemetrySnapshot:
    """Complete observability record for an analyst execution turn."""
    investigation_id: str
    query_count: int
    llm_calls: int
    cache_hits: int
    cache_misses: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    investigation_depth: int
    completeness_score: float
    confidence_score: float
    failed_query_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "query_count": self.query_count,
            "llm_calls": self.llm_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "latency_ms": round(self.latency_ms, 2),
            "investigation_depth": self.investigation_depth,
            "completeness_score": self.completeness_score,
            "confidence_score": self.confidence_score,
            "failed_query_rate": round(self.failed_query_rate, 2),
        }


class SystemMetricsTracker:
    """Collects real-time production efficiency benchmarks and comparison metrics."""

    @staticmethod
    def create_snapshot(
        investigation_id: str,
        query_count: int,
        llm_calls: int,
        cache_hits: int,
        cache_misses: int,
        total_tokens: int,
        latency_ms: float,
        investigation_depth: int = 1,
        completeness_score: float = 100.0,
        confidence_score: float = 1.0,
        failed_queries: int = 0,
    ) -> TelemetrySnapshot:
        # Estimate cost: ~$0.0003 per 1K tokens average
        cost = (total_tokens / 1000.0) * 0.0003
        failed_rate = (failed_queries / query_count) if query_count > 0 else 0.0

        return TelemetrySnapshot(
            investigation_id=investigation_id,
            query_count=query_count,
            llm_calls=llm_calls,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
            investigation_depth=investigation_depth,
            completeness_score=completeness_score,
            confidence_score=confidence_score,
            failed_query_rate=failed_rate,
        )

    @staticmethod
    def compare_benchmarks(
        baseline: TelemetrySnapshot,
        optimized: TelemetrySnapshot,
    ) -> Dict[str, Any]:
        """Compute relative percentage reduction in latency, LLM calls, and cost."""
        lat_reduction = ((baseline.latency_ms - optimized.latency_ms) / baseline.latency_ms * 100.0) if baseline.latency_ms > 0 else 0.0
        cost_reduction = ((baseline.estimated_cost_usd - optimized.estimated_cost_usd) / baseline.estimated_cost_usd * 100.0) if baseline.estimated_cost_usd > 0 else 0.0
        llm_reduction = ((baseline.llm_calls - optimized.llm_calls) / baseline.llm_calls * 100.0) if baseline.llm_calls > 0 else 0.0

        return {
            "latency_reduction_pct": round(lat_reduction, 1),
            "cost_reduction_pct": round(cost_reduction, 1),
            "llm_calls_reduction_pct": round(llm_reduction, 1),
            "cache_hit_improvement": optimized.cache_hits - baseline.cache_hits,
            "accuracy_maintained": optimized.completeness_score >= baseline.completeness_score,
        }
