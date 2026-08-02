from typing import List, Dict
from app.database.discovery.models import DatabaseMetadata, RelationshipEdge, TableMetadata
from app.database.intelligence.interfaces import IRelationshipDetector
from app.database.intelligence.utils import normalize_name

class DeterministicRelationshipDetector(IRelationshipDetector):
    def detect(self, metadata: DatabaseMetadata) -> List[RelationshipEdge]:
        # Start with existing FKs
        edges = list(metadata.relationships)
        
        # Augment by looking for implicit relationships
        tables: Dict[str, TableMetadata] = {}
        schema_for_table: Dict[str, str] = {}
        for schema in metadata.schemas:
            for table in schema.tables:
                tables[normalize_name(table.name)] = table
                schema_for_table[normalize_name(table.name)] = schema.name

        for schema in metadata.schemas:
            for table in schema.tables:
                for col in table.columns:
                    if col.name.endswith("_id") and not col.foreign_key:
                        target_table_norm = normalize_name(col.name[:-3])
                        if target_table_norm in tables:
                            target_table = tables[target_table_norm]
                            target_pk = [c.name for c in target_table.columns if c.primary_key]
                            if target_pk:
                                edge = RelationshipEdge(
                                    source_schema=schema.name,
                                    source_table=table.name,
                                    source_columns=[col.name],
                                    target_schema=schema_for_table[target_table_norm],
                                    target_table=target_table.name,
                                    target_columns=target_pk,
                                    relationship_name=f"implicit_fk_{table.name}_{col.name}"
                                )
                                edges.append(edge)
                                col.foreign_key = True

        return edges
