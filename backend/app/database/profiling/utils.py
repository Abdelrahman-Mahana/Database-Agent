import hashlib
from datetime import datetime

def generate_schema_hash(metadata) -> str:
    # A simple deterministic hash based on table and column names
    content = ""
    for schema in metadata.schemas:
        content += f"schema:{schema.name};"
        for table in schema.tables:
            content += f"table:{table.name};"
            for col in table.columns:
                content += f"col:{col.name}:{col.data_type};"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def generate_profile_id(plugin_name: str) -> str:
    timestamp = datetime.utcnow().strftime('%Y%md%H%M%S')
    return f"prof_{plugin_name}_{timestamp}"
