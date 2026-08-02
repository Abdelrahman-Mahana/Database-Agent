from app.dialect.interfaces import ITranslatorFactory, ITranslatorRegistry, IDialectTranslator

class DeterministicTranslatorFactory(ITranslatorFactory):
    def __init__(self, registry: ITranslatorRegistry):
        self.registry = registry
        
    def get_translator(self, dialect_name: str) -> IDialectTranslator:
        return self.registry.get(dialect_name)
