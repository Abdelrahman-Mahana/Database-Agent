def determine_param_style(dialect_name: str) -> str:
    mapping = {
        "postgresql": "numeric",
        "mysql": "qmark",
        "sqlserver": "at_named",
        "oracle": "named",
        "sqlite": "qmark",
        "snowflake": "qmark",
        "bigquery": "at_named",
        "redshift": "numeric",
        "clickhouse": "named"
    }
    return mapping.get(dialect_name.lower(), "qmark")
