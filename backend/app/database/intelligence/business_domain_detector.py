from typing import List, Dict, Set
from app.database.discovery.models import TableMetadata
from app.database.intelligence.interfaces import IBusinessDomainDetector
from app.database.intelligence.models import DomainConfidence
from app.database.intelligence.utils import normalize_name

class DeterministicDomainDetector(IBusinessDomainDetector):
    def detect(self, tables: List[TableMetadata]) -> List[DomainConfidence]:
        domains = {
            "E-Commerce": ["order", "cart", "product", "customer", "payment", "inventory", "shipping"],
            "Finance": ["transaction", "account", "ledger", "balance", "invoice", "tax", "loan"],
            "Healthcare": ["patient", "doctor", "appointment", "prescription", "medical", "treatment"],
            "Education": ["student", "course", "enrollment", "grade", "class", "teacher", "school"],
            "CRM": ["lead", "contact", "opportunity", "account", "campaign", "ticket"],
            "HR": ["employee", "payroll", "attendance", "leave", "department", "salary"]
        }
        
        domain_matches: Dict[str, Dict[str, Set[str]]] = {
            d: {"tables": set(), "columns": set(), "keywords": set()} for d in domains
        }
        
        for table in tables:
            norm_table_name = normalize_name(table.name)
            for domain, keywords in domains.items():
                for kw in keywords:
                    if kw in norm_table_name:
                        domain_matches[domain]["tables"].add(table.name)
                        domain_matches[domain]["keywords"].add(kw)
            
            for col in table.columns:
                norm_col_name = normalize_name(col.name)
                for domain, keywords in domains.items():
                    for kw in keywords:
                        if kw in norm_col_name:
                            domain_matches[domain]["columns"].add(col.name)
                            domain_matches[domain]["keywords"].add(kw)
        
        total_score = 0
        domain_scores = {}
        for domain, matches in domain_matches.items():
            score = len(matches["tables"]) * 2 + len(matches["columns"])
            domain_scores[domain] = score
            total_score += score
            
        results = []
        if total_score > 0:
            for domain, score in domain_scores.items():
                if score > 0:
                    results.append(DomainConfidence(
                        domain=domain,
                        confidence=round(score / total_score, 2),
                        matched_tables=list(domain_matches[domain]["tables"]),
                        matched_columns=list(domain_matches[domain]["columns"]),
                        matched_keywords=list(domain_matches[domain]["keywords"])
                    ))
        
        return sorted(results, key=lambda x: x.confidence, reverse=True)
