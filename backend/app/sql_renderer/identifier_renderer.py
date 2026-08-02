from app.dialect.models import DialectIdentifier

class IdentifierRenderer:
    def render(self, identifier: DialectIdentifier) -> str:
        quote = identifier.quote_char
        name = identifier.name
        # Simple escaping: duplicate the quote character if it exists inside the identifier
        escaped_name = name.replace(quote, quote * 2)
        return f"{quote}{escaped_name}{quote}"
