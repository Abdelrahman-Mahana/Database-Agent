from typing import Dict
from app.dialect.interfaces import ITranslatorRegistry, IDialectTranslator

class DeterministicTranslatorRegistry(ITranslatorRegistry):
    def __init__(self):
        self._translators: Dict[str, IDialectTranslator] = {}

    def register(self, translator: IDialectTranslator) -> None:
        self._translators[translator.dialect_name.lower()] = translator
        
    def get(self, dialect_name: str) -> IDialectTranslator:
        translator = self._translators.get(dialect_name.lower())
        if not translator:
            raise ValueError(f"Translator for dialect '{dialect_name}' not found.")
        return translator
