import re
from app.query_understanding.interfaces import IQueryNormalizer

class DeterministicQueryNormalizer(IQueryNormalizer):
    def normalize(self, query: str) -> str:
        # Lowercase
        normalized = query.lower()
        # Remove extra spacing
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # Common abbreviations
        replacements = {
            r'\bavg\b': 'average',
            r'\bmin\b': 'minimum',
            r'\bmax\b': 'maximum',
            r'\bnum\b': 'number',
            r'\bqtr\b': 'quarter',
            r'\bqty\b': 'quantity',
            r'\bvs\b': 'versus',
        }
        for pattern, repl in replacements.items():
            normalized = re.sub(pattern, repl, normalized)
            
        return normalized
