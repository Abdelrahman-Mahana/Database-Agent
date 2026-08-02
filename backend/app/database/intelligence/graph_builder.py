from typing import List
from app.database.discovery.models import DatabaseMetadata, RelationshipEdge
from app.database.intelligence.interfaces import IGraphBuilder
from app.database.intelligence.models import IntelligenceGraph, GraphNode, GraphEdge, NodeType, EdgeType

class DeterministicGraphBuilder(IGraphBuilder):
    def build(self, metadata: DatabaseMetadata, relationships: List[RelationshipEdge]) -> IntelligenceGraph:
        graph = IntelligenceGraph()
        
        for schema in metadata.schemas:
            for table in schema.tables:
                node_id = f"{schema.name}.{table.name}"
                graph.nodes.append(GraphNode(
                    id=node_id,
                    label=table.name,
                    type=NodeType.TABLE
                ))
            for view in schema.views:
                node_id = f"{schema.name}.{view.name}"
                graph.nodes.append(GraphNode(
                    id=node_id,
                    label=view.name,
                    type=NodeType.VIEW
                ))
                
        for rel in relationships:
            source_id = f"{rel.source_schema}.{rel.source_table}"
            target_id = f"{rel.target_schema}.{rel.target_table}"
            graph.edges.append(GraphEdge(
                source=source_id,
                target=target_id,
                label=rel.relationship_name,
                type=EdgeType.FK if not rel.relationship_name.startswith("implicit") else EdgeType.INFERRED,
                weight=1.0
            ))
            
        return graph
