from typing import List
from app.context_builder.interfaces import IBuilder, IContextExtractor, IContextOptimizer, IContextValidator
from app.context_builder.models import StructuredContext, ContextBuildRequest

class ContextBuilder(IBuilder):
    def __init__(
        self,
        extractors: List[IContextExtractor],
        optimizer: IContextOptimizer,
        validator: IContextValidator
    ):
        self.extractors = extractors
        self.optimizer = optimizer
        self.validator = validator

    def build(self, request: ContextBuildRequest) -> StructuredContext:
        context = StructuredContext()
        
        for extractor in self.extractors:
            extractor.extract(request, context)
            
        self.optimizer.optimize(request, context)
        
        validation = self.validator.validate(context)
        if not validation.is_valid:
            context.warnings.extend(validation.missing_context)
            context.warnings.extend(validation.conflicting_metadata)
            context.confidence -= 0.2
            
        context.confidence = max(0.0, min(1.0, context.confidence))
        return context
