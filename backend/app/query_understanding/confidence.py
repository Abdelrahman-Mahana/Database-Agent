from typing import List
from app.query_understanding.interfaces import IConfidenceScorer
from app.query_understanding.models import ConfidenceScore, QueryIntent, QueryEntities, QueryAmbiguity

class DeterministicConfidenceScorer(IConfidenceScorer):
    def score(self, intent: QueryIntent, entities: QueryEntities, ambiguities: List[QueryAmbiguity]) -> ConfidenceScore:
        score = 1.0
        reasons = []
        evidence = []
        
        if intent == QueryIntent.UNKNOWN:
            score -= 0.3
            reasons.append("Intent could not be determined.")
        else:
            evidence.append(f"Detected intent: {intent.value}")
            
        if ambiguities:
            penalty = min(len(ambiguities) * 0.2, 0.5)
            score -= penalty
            reasons.append(f"Found {len(ambiguities)} ambiguities in the query.")
            
        if not entities.tables and not entities.columns:
            score -= 0.2
            reasons.append("No database entities found in the query.")
        else:
            evidence.append(f"Found tables: {entities.tables}")
            
        score = max(0.0, score)
        return ConfidenceScore(score=score, evidence=evidence, reasons=reasons)
