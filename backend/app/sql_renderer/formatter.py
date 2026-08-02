import sqlparse

class SQLFormatter:
    def format(self, raw_sql: str) -> str:
        # Generate readable SQL
        return sqlparse.format(
            raw_sql,
            reindent=True,
            keyword_case='upper',
            strip_comments=True
        )
