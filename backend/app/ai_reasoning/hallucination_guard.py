from typing import List
import re
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IHallucinationGuard

class HallucinationGuard(IHallucinationGuard):
    def validate(self, answer: str, context: StructuredContext) -> List[str]:
        failures = []
        answer_lower = answer.lower()
        
        # Rule 1: No SQL leakage
        if "select " in answer_lower and " from " in answer_lower:
            failures.append("SQL query leaked in response.")
            
        # Rule 2: Dialect Hallucination
        dialect = context.database_context.dialect.lower()
        dialects = {"postgres", "mysql", "sqlserver", "oracle"}
        for d in dialects:
            if d in answer_lower and d != dialect:
                failures.append(f"Hallucinated database dialect '{d}' (Actual: {dialect}).")

        # Rule 3: Ensure metrics mentioned are backed by context
        if "null ratio" in answer_lower:
            qm = context.semantic_context.quality_metrics
            if not qm or "null_ratio" not in qm:
                 failures.append("Referenced null ratio without semantic backing.")

        return failures
