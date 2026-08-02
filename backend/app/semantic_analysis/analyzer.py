import time
from typing import Dict, List, Any
from app.result_processing.models import ProcessedResult
from app.semantic_analysis.interfaces import (
    IAnalyzer, IColumnClassifier, IQualityAnalyzer, IDistributionAnalyzer,
    IOutlierDetector, IRelationshipDetector, IStatisticsEngine, IMetadataBuilder
)
from app.semantic_analysis.models import SemanticAnalysisResult, ColumnProfile, DatasetProfile, SemanticClass
from app.semantic_analysis.numeric_analyzer import NumericAnalyzer
from app.semantic_analysis.categorical_analyzer import CategoricalAnalyzer
from app.semantic_analysis.temporal_analyzer import TemporalAnalyzer
from app.semantic_analysis.text_analyzer import TextAnalyzer

class SemanticAnalyzer(IAnalyzer):
    def __init__(
        self,
        classifier: IColumnClassifier,
        quality_analyzer: IQualityAnalyzer,
        distribution_analyzer: IDistributionAnalyzer,
        outlier_detector: IOutlierDetector,
        relationship_detector: IRelationshipDetector,
        statistics_engine: IStatisticsEngine,
        metadata_builder: IMetadataBuilder
    ):
        self.classifier = classifier
        self.quality_analyzer = quality_analyzer
        self.distribution_analyzer = distribution_analyzer
        self.outlier_detector = outlier_detector
        self.relationship_detector = relationship_detector
        self.statistics_engine = statistics_engine
        self.metadata_builder = metadata_builder

        self.num_analyzer = NumericAnalyzer()
        self.cat_analyzer = CategoricalAnalyzer()
        self.time_analyzer = TemporalAnalyzer()
        self.text_analyzer = TextAnalyzer()

    def analyze(self, result: ProcessedResult) -> SemanticAnalysisResult:
        start_time = time.time()
        
        profiles: Dict[str, ColumnProfile] = {}
        rows = result.rows
        
        # Dataset Profile
        dataset_profile = DatasetProfile(
            row_count=len(rows),
            column_count=len(result.schema_def.columns),
            total_cells=len(rows) * len(result.schema_def.columns)
        )
        missing_cells = 0

        # Build column data mapping
        col_data = {col.name: [] for col in result.schema_def.columns}
        for row in rows:
            for col in result.schema_def.columns:
                val = row.get(col.name)
                col_data[col.name].append(val)
                if val is None:
                    missing_cells += 1

        dataset_profile.missing_cells = missing_cells
        dataset_profile.overall_completeness = 1.0 - (missing_cells / dataset_profile.total_cells if dataset_profile.total_cells > 0 else 0)

        # Profile each column
        for col in result.schema_def.columns:
            values = col_data[col.name]
            sem_class = self.classifier.classify(col, values)
            
            profile = ColumnProfile(
                name=col.name,
                semantic_class=sem_class,
                quality=self.quality_analyzer.analyze(values),
                distribution=self.distribution_analyzer.analyze(values, sem_class),
                outliers=self.outlier_detector.detect_outliers(values, sem_class)
            )
            
            if sem_class == SemanticClass.NUMERIC:
                profile.statistics = self.num_analyzer.analyze(values)
            elif sem_class == SemanticClass.CATEGORICAL:
                profile.statistics = self.cat_analyzer.analyze(values)
            elif sem_class == SemanticClass.TEMPORAL:
                profile.statistics = self.time_analyzer.analyze(values)
            elif sem_class == SemanticClass.TEXT:
                profile.statistics = self.text_analyzer.analyze(values)
                
            profiles[col.name] = profile

        # Relationships
        rels = self.relationship_detector.detect(profiles, rows)
        
        # Global Statistics
        stats = self.statistics_engine.compute(profiles)
        
        processing_time_ms = (time.time() - start_time) * 1000

        return self.metadata_builder.build(
            result=result,
            profiles=profiles,
            dataset=dataset_profile,
            rels=rels,
            stats=stats,
            processing_time_ms=processing_time_ms
        )
