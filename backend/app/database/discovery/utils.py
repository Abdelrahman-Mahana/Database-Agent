def parse_db_version(version_info) -> str:
    """Utility to parse dialect version tuples to string."""
    if isinstance(version_info, tuple):
        return ".".join(map(str, version_info))
    return str(version_info)
