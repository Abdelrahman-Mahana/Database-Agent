from app.query_understanding.interfaces import IIntentClassifier
from app.query_understanding.models import QueryIntent

class KeywordIntentClassifier(IIntentClassifier):
    def classify(self, normalized_query: str) -> QueryIntent:
        # Ordered by specificity
        if any(w in normalized_query for w in ["explain", "why", "how come"]):
            return QueryIntent.EXPLAIN
        if any(w in normalized_query for w in ["compare", "versus", "vs", "difference between"]):
            return QueryIntent.COMPARE
        if any(w in normalized_query for w in ["trend", "over time", "history", "historical"]):
            return QueryIntent.TREND
        if any(w in normalized_query for w in ["top", "highest", "best", "most"]):
            return QueryIntent.TOP_K
        if any(w in normalized_query for w in ["bottom", "lowest", "worst", "least"]):
            return QueryIntent.BOTTOM_K
        if any(w in normalized_query for w in ["summary", "summarize", "overview"]):
            return QueryIntent.SUMMARY
        if any(w in normalized_query for w in ["count", "how many"]):
            return QueryIntent.COUNT
        if any(w in normalized_query for w in ["average", "sum", "total", "minimum", "maximum"]):
            return QueryIntent.AGGREGATION
        if any(w in normalized_query for w in ["describe", "what is"]):
            return QueryIntent.DESCRIBE
        if any(w in normalized_query for w in ["show", "get", "list", "find", "select"]):
            return QueryIntent.SELECT
            
        return QueryIntent.UNKNOWN
