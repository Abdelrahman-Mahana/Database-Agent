import re

def normalize_name(name: str) -> str:
    """Normalize a name for comparison by lowering it and removing underscores."""
    if not name:
        return ""
    return re.sub(r'[^a-z0-9]', '', name.lower())
