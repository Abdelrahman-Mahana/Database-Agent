import hashlib

def generate_query_hash(plugin_name: str, query: str) -> str:
    content = f"{plugin_name}:{query.lower().strip()}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()
