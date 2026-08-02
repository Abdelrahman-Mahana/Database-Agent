from typing import List, Dict, Any
from app.semantic_analysis.interfaces import IStatisticsEngine, IQualityAnalyzer, IDistributionAnalyzer, IOutlierDetector
from app.semantic_analysis.models import ColumnProfile, SemanticClass
from app.semantic_analysis.numeric_analyzer import NumericAnalyzer
from app.semantic_analysis.categorical_analyzer import CategoricalAnalyzer
from app.semantic_analysis.text_analyzer import TextAnalyzer
from app.semantic_analysis.temporal_analyzer import TemporalAnalyzer

class StatisticsEngine(IStatisticsEngine):
    def __init__(self, quality_analyzer: IQualityAnalyzer, distribution_analyzer: IDistributionAnalyzer, outlier_detector: IOutlierDetector):
        self.quality_analyzer = quality_analyzer
        self.distribution_analyzer = distribution_analyzer
        self.outlier_detector = outlier_detector
        
        self.numeric_analyzer = NumericAnalyzer()
        self.categorical_analyzer = CategoricalAnalyzer()
        self.text_analyzer = TextAnalyzer()
        self.temporal_analyzer = TemporalAnalyzer()

    def compute(self, profiles: Dict[str, ColumnProfile]) -> Dict[str, Any]:
        # Statistics engine typically aggregates column level stats to dataset level or delegates execution.
        # Since we compute per column in Analyzer, we just return a summary here.
        num_cols = sum(1 for p in profiles.values() if p.semantic_class == SemanticClass.NUMERIC)
        cat_cols = sum(1 for p in profiles.values() if p.semantic_class == SemanticClass.CATEGORICAL)
        return {
            "total_columns": len(profiles),
            "numeric_columns": num_cols,
            "categorical_columns": cat_cols,
            "identifier_columns": sum(1 for p in profiles.values() if p.semantic_class == SemanticClass.IDENTIFIER)
        }
