from app.context_builder.interfaces import IRankingEngine
from app.context_builder.models import StructuredContext, ContextBuildRequest

class RankingEngine(IRankingEngine):
    def rank(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        entities = set(e.lower() for e in context.relevant_entities)
        
        tables = context.schema_context.tables
        if tables:
            for t_name, t_data in tables.items():
                score = 1.0
                
                # Signal 1: Query Understanding (Entity Match)
                if any(e in t_name.lower() for e in entities):
                    score += 5.0
                    
                # Signal 2: Semantic Analysis (Relationship Graph)
                rels = context.semantic_context.relationships.get("candidate_foreign_keys", {})
                if t_name in rels or any(t_name in str(v) for v in rels.values()):
                    score += 2.0
                    
                # Signal 3: Execution Plan / Usage
                nodes = context.planning_context.nodes
                if nodes and any(t_name.lower() in str(n).lower() for n in nodes):
                    score += 10.0
                
                t_data.relevance_score = score
                
                # Column Ranking
                for c_name, c_data in t_data.columns.items():
                    c_score = 1.0
                    if any(e in c_name.lower() for e in entities):
                        c_score += 3.0
                    if c_name in rels.get(t_name, []):
                        c_score += 2.0
                    c_data.relevance_score = c_score
                
            # Sort tables descending
            context.schema_context.tables = dict(
                sorted(tables.items(), key=lambda item: item[1].relevance_score, reverse=True)
            )
