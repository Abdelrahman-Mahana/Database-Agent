from dependency_injector import containers, providers
from app.config.settings import Settings
from app.plugins.manager import PluginManager
from app.database.discovery.cache import DiscoveryCache
from app.database.discovery.service import DiscoveryService
from app.database.intelligence.relationship_detector import DeterministicRelationshipDetector
from app.database.intelligence.semantic_classifier import DeterministicSemanticClassifier
from app.database.intelligence.table_classifier import DeterministicTableClassifier
from app.database.intelligence.business_domain_detector import DeterministicDomainDetector
from app.database.intelligence.graph_builder import DeterministicGraphBuilder
from app.database.intelligence.service import SchemaIntelligenceService
from app.database.profiling.cache import ProfilingCache
from app.database.profiling.sampling import StrategyFactory
from app.database.profiling.factory import ProfilerFactory
from app.database.profiling.profilers.numeric import NumericProfiler
from app.database.profiling.profilers.categorical import CategoricalProfiler
from app.database.profiling.profilers.text import TextProfiler
from app.database.profiling.profilers.datetime import DatetimeProfiler
from app.database.profiling.statistics_collector import StatisticsCollector
from app.database.profiling.service import DataProfilingService

from app.query_understanding.query_normalizer import DeterministicQueryNormalizer
from app.query_understanding.intent_classifier import KeywordIntentClassifier
from app.query_understanding.entity_extractor import KeywordEntityExtractor
from app.query_understanding.metric_detector import DeterministicMetricDetector
from app.query_understanding.dimension_detector import DeterministicDimensionDetector
from app.query_understanding.filter_extractor import RegexFilterExtractor
from app.query_understanding.time_parser import DeterministicTimeParser
from app.query_understanding.ambiguity_detector import DeterministicAmbiguityDetector
from app.query_understanding.context_builder import DeterministicContextBuilder
from app.query_understanding.router import DeterministicRouter
from app.query_understanding.confidence import DeterministicConfidenceScorer
from app.query_understanding.cache import QueryUnderstandingCache
from app.query_understanding.service import QueryUnderstandingService

from app.planning.step_builder import DeterministicStepBuilder
from app.planning.join_planner import DeterministicJoinPlanner
from app.planning.aggregation_planner import DeterministicAggregationPlanner
from app.planning.filter_planner import DeterministicFilterPlanner
from app.planning.sort_planner import DeterministicSortPlanner
from app.planning.limit_planner import DeterministicLimitPlanner
from app.planning.dependency_resolver import DeterministicDependencyResolver
from app.planning.plan_optimizer import DeterministicPlanOptimizer
from app.planning.planner import DeterministicExecutionPlanner
from app.planning.cache import ExecutionPlanCache
from app.planning.service import ExecutionPlanningService

from app.logical_query.expression_builder import DeterministicExpressionBuilder
from app.logical_query.join_graph import DeterministicJoinGraph
from app.logical_query.projection_builder import DeterministicProjectionBuilder
from app.logical_query.aggregation_builder import DeterministicAggregationBuilder
from app.logical_query.filter_builder import DeterministicFilterBuilder
from app.logical_query.sort_builder import DeterministicSortBuilder
from app.logical_query.limit_builder import DeterministicLimitBuilder
from app.logical_query.builder import DeterministicLogicalQueryBuilder
from app.logical_query.optimizer import DeterministicLogicalOptimizer
from app.logical_query.cache import LogicalQueryCache
from app.logical_query.service import LogicalQueryService

from app.dialect.translator_registry import DeterministicTranslatorRegistry
from app.dialect.translator_factory import DeterministicTranslatorFactory
from app.dialect.ast_builder import DeterministicAstBuilder
from app.dialect.optimizer import DeterministicDialectOptimizer
from app.dialect.cache import DialectCache
from app.dialect.service import DialectTranslationService

from app.dialect.translators.postgresql import PostgreSQLTranslator
from app.dialect.translators.mysql import MySQLTranslator
from app.dialect.translators.sqlserver import SQLServerTranslator
from app.dialect.translators.oracle import OracleTranslator
from app.dialect.translators.sqlite import SQLiteTranslator
from app.dialect.translators.snowflake import SnowflakeTranslator
from app.dialect.translators.bigquery import BigQueryTranslator
from app.dialect.translators.redshift import RedshiftTranslator
from app.dialect.translators.clickhouse import ClickHouseTranslator

from app.sql_renderer.renderer_registry import DeterministicRendererRegistry
from app.sql_renderer.renderer_factory import DeterministicRendererFactory
from app.sql_renderer.identifier_renderer import IdentifierRenderer
from app.sql_renderer.expression_renderer import ExpressionRenderer
from app.sql_renderer.projection_renderer import ProjectionRenderer
from app.sql_renderer.join_renderer import JoinRenderer
from app.sql_renderer.filter_renderer import FilterRenderer
from app.sql_renderer.groupby_renderer import GroupByRenderer
from app.sql_renderer.orderby_renderer import OrderByRenderer
from app.sql_renderer.limit_renderer import LimitRenderer
from app.sql_renderer.formatter import SQLFormatter
from app.sql_renderer.cache import SQLCache
from app.sql_renderer.service import SQLRenderingService

from app.sql_validation.statement_validator import StatementValidator
from app.sql_validation.ast_validator import AstValidator
from app.sql_validation.complexity_validator import ComplexityValidator
from app.sql_validation.row_limit_validator import RowLimitValidator
from app.sql_validation.timeout_validator import TimeoutValidator
from app.sql_validation.permission_checker import PermissionChecker
from app.sql_validation.validator import CompositeValidator
from app.sql_validation.registry import PolicyRegistry
from app.sql_validation.factory import PolicyFactory
from app.sql_validation.cache import ValidationCache
from app.sql_validation.service import SQLValidationService
from app.sql_validation.policies.analyst import AnalystPolicy
from app.sql_validation.policies.readonly import ReadOnlyPolicy
from app.sql_validation.policies.admin import AdminPolicy

from app.execution.cancellation_manager import CancellationManager
from app.execution.retry_manager import RetryManager
from app.execution.timeout_manager import TimeoutManager
from app.execution.transaction_manager import TransactionManager
from app.execution.connection_manager import ConnectionManager
from app.execution.session_manager import SessionManager
from app.execution.executor import DeterministicExecutor
from app.execution.factory import ExecutorFactory, ExecutionRegistry
from app.execution.cache import ExecutionCache
from app.execution.metrics import MetricsCollector
from app.execution.service import ExecutionService

from app.result_processing.type_normalizer import DeterministicTypeNormalizer
from app.result_processing.metadata_extractor import DeterministicMetadataExtractor
from app.result_processing.chunk_reader import DeterministicChunkReader
from app.result_processing.processor import Processor
from app.result_processing.stream_processor import StreamProcessor
from app.result_processing.serializer import ResultSerializer
from app.result_processing.cache import ResultCache as RPCache
from app.result_processing.metrics import MetricsLogger as RPMetricsLogger
from app.result_processing.service import ResultProcessingService

from app.semantic_analysis.column_classifier import ColumnClassifier
from app.semantic_analysis.missing_value_analyzer import QualityAnalyzer
from app.semantic_analysis.distribution_analyzer import DistributionAnalyzer
from app.semantic_analysis.outlier_detector import OutlierDetector
from app.semantic_analysis.correlation_analyzer import CorrelationAnalyzer
from app.semantic_analysis.relationship_detector import RelationshipDetector
from app.semantic_analysis.statistics_engine import StatisticsEngine
from app.semantic_analysis.metadata_builder import MetadataBuilder
from app.semantic_analysis.analyzer import SemanticAnalyzer
from app.semantic_analysis.factory import AnalyzerRegistry, AnalyzerFactory
from app.semantic_analysis.cache import SemanticCache
from app.semantic_analysis.metrics import SemanticMetricsCollector
from app.semantic_analysis.service import SemanticAnalysisService

from app.context_builder.schema_context import SchemaContextExtractor
from app.context_builder.profiling_context import ProfilingContextExtractor
from app.context_builder.semantic_context import SemanticContextExtractor
from app.context_builder.planning_context import PlanningContextExtractor
from app.context_builder.question_context import QuestionContextExtractor
from app.context_builder.execution_context import ExecutionContextExtractor
from app.context_builder.ranking_engine import RankingEngine
from app.context_builder.token_estimator import TokenEstimator, OpenAITokenProvider
from app.context_builder.compressor import ContextCompressor
from app.context_builder.context_optimizer import ContextOptimizer
from app.context_builder.context_validator import ContextValidator
from app.context_builder.builder import ContextBuilder
from app.context_builder.factory import BuilderRegistry, BuilderFactory
from app.context_builder.cache import ContextCache as CBCache
from app.context_builder.metrics import ContextMetricsCollector
from app.context_builder.service import ContextBuilderService

from app.ai_reasoning.prompt_builder import PromptBuilder
from app.ai_reasoning.provider_router import ProviderRouter
from app.ai_reasoning.reasoning_trace import ReasoningTraceBuilder
from app.ai_reasoning.hallucination_guard import HallucinationGuard
from app.ai_reasoning.response_validator import ResponseValidator
from app.ai_reasoning.citation_builder import CitationBuilder
from app.ai_reasoning.confidence_engine import ConfidenceEngine
from app.ai_reasoning.recommendation_engine import RecommendationEngine
from app.ai_reasoning.followup_generator import FollowupGenerator
from app.ai_reasoning.explanation_engine import ExplanationEngine
from app.ai_reasoning.answer_generator import AnswerGenerator
from app.ai_reasoning.reasoning_engine import ReasoningEngine
from app.ai_reasoning.llm_provider import OpenAIProvider, GeminiProvider, ClaudeProvider, LocalLLMProvider
from app.ai_reasoning.factory import ReasoningEngineRegistry, ReasoningEngineFactory
from app.ai_reasoning.cache import ReasoningCache
from app.ai_reasoning.metrics import ReasoningMetricsCollector
from app.ai_reasoning.service import AIReasoningService

from app.conversation.session_manager import SessionManager
from app.conversation.memory_cache import MemoryCache
from app.conversation.short_term_memory import ShortTermMemory
from app.conversation.long_term_memory import LongTermMemory
from app.conversation.history_compressor import HistoryCompressor
from app.conversation.memory_manager import MemoryManager
from app.conversation.entity_tracker import EntityTracker
from app.conversation.reference_resolver import ReferenceResolver
from app.conversation.intent_resolver import IntentResolver
from app.conversation.context_reuse import ContextReuse
from app.conversation.context_resolver import ContextResolver
from app.conversation.conversation_validator import ConversationValidator
from app.conversation.ttl_manager import TTLManager
from app.conversation.conversation_manager import ConversationManager
from app.conversation.factory import ConversationManagerRegistry, ConversationManagerFactory
from app.conversation.metrics import ConversationMetricsCollector
from app.conversation.service import ConversationService

from app.orchestrator.event_bus import EventBus
from app.orchestrator.state_machine import StateMachine
from app.orchestrator.retry_manager import RetryManager
from app.orchestrator.timeout_manager import TimeoutManager
from app.orchestrator.fallback_manager import FallbackManager
from app.orchestrator.decision_engine import DecisionEngine
from app.orchestrator.clarification_engine import ClarificationEngine
from app.orchestrator.context_reuse_engine import ContextReuseEngine
from app.orchestrator.execution_graph import ExecutionGraph
from app.orchestrator.routing_engine import RoutingEngine
from app.orchestrator.workflow_engine import WorkflowEngine
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.factory import OrchestratorRegistry, OrchestratorFactory
from app.orchestrator.metrics import OrchestratorMetricsCollector
from app.orchestrator.service import OrchestratorService

from app.sql_renderer.renderers.postgresql import PostgreSQLRenderer
from app.sql_renderer.renderers.mysql import MySQLRenderer
from app.sql_renderer.renderers.sqlserver import SQLServerRenderer
from app.sql_renderer.renderers.oracle import OracleRenderer
from app.sql_renderer.renderers.sqlite import SQLiteRenderer
from app.sql_renderer.renderers.snowflake import SnowflakeRenderer
from app.sql_renderer.renderers.bigquery import BigQueryRenderer
from app.sql_renderer.renderers.redshift import RedshiftRenderer
from app.sql_renderer.renderers.clickhouse import ClickHouseRenderer

class Container(containers.DeclarativeContainer):
    """
    DI Container for the application.
    """
    wiring_config = containers.WiringConfiguration(
        packages=["app.api", "app.services"]
    )
    
    settings = providers.Configuration(pydantic_settings=[Settings()])
    
    plugin_manager = providers.Singleton(PluginManager)
    
    discovery_cache = providers.Singleton(DiscoveryCache)
    
    discovery_service = providers.Factory(
        DiscoveryService,
        plugin_manager=plugin_manager,
        cache=discovery_cache,
    )
    
    relationship_detector = providers.Singleton(DeterministicRelationshipDetector)
    semantic_classifier = providers.Singleton(DeterministicSemanticClassifier)
    table_classifier = providers.Singleton(DeterministicTableClassifier)
    domain_detector = providers.Singleton(DeterministicDomainDetector)
    graph_builder = providers.Singleton(DeterministicGraphBuilder)
    
    intelligence_service = providers.Singleton(
        SchemaIntelligenceService,
        discovery_service=discovery_service,
        relationship_detector=relationship_detector,
        semantic_classifier=semantic_classifier,
        table_classifier=table_classifier,
        domain_detector=domain_detector,
        graph_builder=graph_builder
    )
    
    profiling_cache = providers.Singleton(ProfilingCache)
    
    strategy_factory = providers.Singleton(StrategyFactory, settings=settings)
    numeric_profiler = providers.Singleton(NumericProfiler, settings=settings)
    categorical_profiler = providers.Singleton(CategoricalProfiler, settings=settings)
    text_profiler = providers.Singleton(TextProfiler, settings=settings)
    datetime_profiler = providers.Singleton(DatetimeProfiler, settings=settings)
    
    profiler_factory = providers.Singleton(
        ProfilerFactory,
        numeric_profiler=numeric_profiler,
        categorical_profiler=categorical_profiler,
        text_profiler=text_profiler,
        datetime_profiler=datetime_profiler
    )
    
    statistics_collector = providers.Factory(
        StatisticsCollector,
        settings=settings,
        strategy_factory=strategy_factory,
        profiler_factory=profiler_factory
    )
    
    profiling_service = providers.Singleton(
        DataProfilingService,
        discovery_service=discovery_service,
        collector=statistics_collector,
        cache=profiling_cache
    )
    
    # Query Understanding
    qu_normalizer = providers.Singleton(DeterministicQueryNormalizer)
    qu_intent_classifier = providers.Singleton(KeywordIntentClassifier)
    qu_entity_extractor = providers.Singleton(KeywordEntityExtractor)
    qu_metric_detector = providers.Singleton(DeterministicMetricDetector)
    qu_dimension_detector = providers.Singleton(DeterministicDimensionDetector)
    qu_filter_extractor = providers.Singleton(RegexFilterExtractor)
    qu_time_parser = providers.Singleton(DeterministicTimeParser)
    qu_ambiguity_detector = providers.Singleton(DeterministicAmbiguityDetector)
    qu_context_builder = providers.Singleton(DeterministicContextBuilder)
    qu_router = providers.Singleton(DeterministicRouter)
    qu_confidence_scorer = providers.Singleton(DeterministicConfidenceScorer)
    qu_cache = providers.Singleton(QueryUnderstandingCache)
    
    query_understanding_service = providers.Singleton(
        QueryUnderstandingService,
        normalizer=qu_normalizer,
        intent_classifier=qu_intent_classifier,
        entity_extractor=qu_entity_extractor,
        metric_detector=qu_metric_detector,
        dimension_detector=qu_dimension_detector,
        filter_extractor=qu_filter_extractor,
        time_parser=qu_time_parser,
        ambiguity_detector=qu_ambiguity_detector,
        context_builder=qu_context_builder,
        router=qu_router,
        confidence_scorer=qu_confidence_scorer,
        cache=qu_cache,
        discovery_service=discovery_service,
        intelligence_service=intelligence_service,
        profiling_service=profiling_service
    )
    
    # Execution Planning
    plan_step_builder = providers.Singleton(DeterministicStepBuilder)
    plan_join_planner = providers.Singleton(DeterministicJoinPlanner)
    plan_aggregation_planner = providers.Singleton(DeterministicAggregationPlanner)
    plan_filter_planner = providers.Singleton(DeterministicFilterPlanner)
    plan_sort_planner = providers.Singleton(DeterministicSortPlanner)
    plan_limit_planner = providers.Singleton(DeterministicLimitPlanner)
    plan_dependency_resolver = providers.Singleton(DeterministicDependencyResolver)
    plan_optimizer = providers.Singleton(DeterministicPlanOptimizer)
    plan_cache = providers.Singleton(ExecutionPlanCache)
    
    execution_planner = providers.Singleton(
        DeterministicExecutionPlanner,
        step_builder=plan_step_builder,
        join_planner=plan_join_planner,
        aggregation_planner=plan_aggregation_planner,
        filter_planner=plan_filter_planner,
        sort_planner=plan_sort_planner,
        limit_planner=plan_limit_planner,
        dependency_resolver=plan_dependency_resolver,
        optimizer=plan_optimizer
    )
    
    execution_planning_service = providers.Singleton(
        ExecutionPlanningService,
        planner=execution_planner,
        cache=plan_cache,
        qu_service=query_understanding_service,
        intelligence_service=intelligence_service,
        profiling_service=profiling_service
    )
    
    # Logical Query Model
    lq_expression_builder = providers.Singleton(DeterministicExpressionBuilder)
    lq_join_graph = providers.Singleton(DeterministicJoinGraph)
    lq_projection_builder = providers.Singleton(DeterministicProjectionBuilder)
    lq_aggregation_builder = providers.Singleton(DeterministicAggregationBuilder)
    lq_filter_builder = providers.Singleton(DeterministicFilterBuilder)
    lq_sort_builder = providers.Singleton(DeterministicSortBuilder)
    lq_limit_builder = providers.Singleton(DeterministicLimitBuilder)
    
    lq_builder = providers.Singleton(
        DeterministicLogicalQueryBuilder,
        join_graph=lq_join_graph,
        projection_builder=lq_projection_builder,
        aggregation_builder=lq_aggregation_builder,
        filter_builder=lq_filter_builder,
        sort_builder=lq_sort_builder,
        limit_builder=lq_limit_builder
    )
    
    lq_optimizer = providers.Singleton(DeterministicLogicalOptimizer)
    lq_cache = providers.Singleton(LogicalQueryCache)
    
    logical_query_service = providers.Singleton(
        LogicalQueryService,
        builder=lq_builder,
        optimizer=lq_optimizer,
        cache=lq_cache,
        planning_service=execution_planning_service
    )
    
    # Dialect Translation Model
    
    dialect_pg = providers.Singleton(PostgreSQLTranslator)
    dialect_mysql = providers.Singleton(MySQLTranslator)
    dialect_sqlserver = providers.Singleton(SQLServerTranslator)
    dialect_oracle = providers.Singleton(OracleTranslator)
    dialect_sqlite = providers.Singleton(SQLiteTranslator)
    dialect_snowflake = providers.Singleton(SnowflakeTranslator)
    dialect_bigquery = providers.Singleton(BigQueryTranslator)
    dialect_redshift = providers.Singleton(RedshiftTranslator)
    dialect_clickhouse = providers.Singleton(ClickHouseTranslator)
    
    dialect_registry = providers.Singleton(DeterministicTranslatorRegistry)
    
    # This is a bit of manual wiring for the registry post-init, but in Dependency Injector 
    # it's usually better to do this in application startup, or pass them in a list.
    # For now, we will pass them via init if possible, or initialize them here.
    
    dialect_factory = providers.Singleton(
        DeterministicTranslatorFactory,
        registry=dialect_registry
    )
    
    dialect_ast_builder = providers.Singleton(DeterministicAstBuilder)
    dialect_optimizer = providers.Singleton(DeterministicDialectOptimizer)
    dialect_cache = providers.Singleton(DialectCache)
    
    dialect_service = providers.Singleton(
        DialectTranslationService,
        factory=dialect_factory,
        ast_builder=dialect_ast_builder,
        optimizer=dialect_optimizer,
        cache=dialect_cache,
        logical_query_service=logical_query_service
    )
    
    # SQL Rendering Model
    sql_ident_renderer = providers.Singleton(IdentifierRenderer)
    
    sql_expr_renderer = providers.Singleton(
        ExpressionRenderer,
        ident_renderer=sql_ident_renderer
    )
    
    sql_proj_renderer = providers.Singleton(
        ProjectionRenderer,
        expr_renderer=sql_expr_renderer
    )
    
    sql_join_renderer = providers.Singleton(
        JoinRenderer,
        expr_renderer=sql_expr_renderer,
        ident_renderer=sql_ident_renderer
    )
    
    sql_filter_renderer = providers.Singleton(
        FilterRenderer,
        expr_renderer=sql_expr_renderer
    )
    
    sql_group_renderer = providers.Singleton(
        GroupByRenderer,
        expr_renderer=sql_expr_renderer
    )
    
    sql_order_renderer = providers.Singleton(
        OrderByRenderer,
        expr_renderer=sql_expr_renderer
    )
    
    sql_limit_renderer = providers.Singleton(LimitRenderer)
    
    sql_formatter = providers.Singleton(SQLFormatter)
    
    sql_pg_renderer = providers.Singleton(
        PostgreSQLRenderer,
        ident_renderer=sql_ident_renderer,
        expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer,
        join_renderer=sql_join_renderer,
        filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer,
        order_renderer=sql_order_renderer,
        limit_renderer=sql_limit_renderer,
        formatter=sql_formatter
    )
    
    sql_mysql_renderer = providers.Singleton(
        MySQLRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_sqlserver_renderer = providers.Singleton(
        SQLServerRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_oracle_renderer = providers.Singleton(
        OracleRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_sqlite_renderer = providers.Singleton(
        SQLiteRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_snowflake_renderer = providers.Singleton(
        SnowflakeRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_bigquery_renderer = providers.Singleton(
        BigQueryRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_redshift_renderer = providers.Singleton(
        RedshiftRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_clickhouse_renderer = providers.Singleton(
        ClickHouseRenderer, ident_renderer=sql_ident_renderer, expr_renderer=sql_expr_renderer,
        proj_renderer=sql_proj_renderer, join_renderer=sql_join_renderer, filter_renderer=sql_filter_renderer,
        group_renderer=sql_group_renderer, order_renderer=sql_order_renderer, limit_renderer=sql_limit_renderer, formatter=sql_formatter
    )
    
    sql_registry = providers.Singleton(DeterministicRendererRegistry)
    
    sql_factory = providers.Singleton(
        DeterministicRendererFactory,
        registry=sql_registry
    )
    
    sql_cache = providers.Singleton(SQLCache)
    
    sql_rendering_service = providers.Singleton(
        SQLRenderingService,
        factory=sql_factory,
        cache=sql_cache,
        dialect_service=dialect_service
    )
    
    # SQL Validation Model
    
    val_stmt = providers.Singleton(StatementValidator)
    val_ast = providers.Singleton(AstValidator)
    val_complexity = providers.Singleton(ComplexityValidator, max_joins=5)
    val_row_limit = providers.Singleton(RowLimitValidator, max_rows=1000)
    val_timeout = providers.Singleton(TimeoutValidator, max_complexity_level="HIGH")
    val_permission = providers.Singleton(PermissionChecker)
    
    # Define standard policies based on composite groups of validators
    val_analyst_policy = providers.Singleton(
        AnalystPolicy,
        stmt_val=val_stmt, ast_val=val_ast, comp_val=val_complexity, 
        limit_val=val_row_limit, to_val=val_timeout, perm_val=val_permission
    )
    
    val_readonly_policy = providers.Singleton(
        ReadOnlyPolicy,
        stmt_val=val_stmt, ast_val=val_ast, perm_val=val_permission
    )
    
    val_admin_policy = providers.Singleton(
        AdminPolicy,
        stmt_val=val_stmt, ast_val=val_ast
    )
    
    val_registry = providers.Singleton(PolicyRegistry)
    
    val_factory = providers.Singleton(
        PolicyFactory,
        registry=val_registry
    )
    
    val_engine = providers.Singleton(
        __import__('app.sql_validation.policy_engine', fromlist=['DeterministicPolicyEngine']).DeterministicPolicyEngine,
        policies=providers.List(
            val_analyst_policy,
            val_readonly_policy,
            val_admin_policy
        )
    )
    
    val_cache = providers.Singleton(ValidationCache)
    
    sql_validation_service = providers.Singleton(
        SQLValidationService,
        engine=val_engine,
        cache=val_cache,
        sql_renderer_service=sql_rendering_service,
        dialect_service=dialect_service
    )
    
    # Execution Engine
    
    exec_cancel = providers.Singleton(CancellationManager)
    exec_retry = providers.Singleton(RetryManager, max_retries=3, base_delay=0.5)
    exec_timeout = providers.Singleton(TimeoutManager)
    exec_tx = providers.Singleton(TransactionManager)
    exec_conn_mgr = providers.Singleton(ConnectionManager)
    
    exec_session = providers.Singleton(
        SessionManager,
        connection_manager=exec_conn_mgr,
        transaction_manager=exec_tx
    )
    
    exec_deterministic_executor = providers.Singleton(
        DeterministicExecutor,
        session_manager=exec_session,
        cancellation_manager=exec_cancel,
        retry_manager=exec_retry,
        timeout_manager=exec_timeout
    )
    
    exec_registry = providers.Singleton(ExecutionRegistry)
    
    exec_factory = providers.Singleton(
        ExecutorFactory,
        registry=exec_registry,
        default_executor=exec_deterministic_executor
    )
    
    exec_cache = providers.Singleton(ExecutionCache)
    exec_metrics = providers.Singleton(MetricsCollector)
    
    execution_service = providers.Singleton(
        ExecutionService,
        executor_factory=exec_factory,
        cancellation_manager=exec_cancel,
        sql_rendering_service=sql_rendering_service,
        cache=exec_cache,
        metrics=exec_metrics
    )
    
    # Result Processing Engine
    rp_normalizer = providers.Singleton(DeterministicTypeNormalizer)
    rp_metadata = providers.Singleton(DeterministicMetadataExtractor, normalizer=rp_normalizer)
    rp_chunk_reader = providers.Singleton(DeterministicChunkReader)
    
    rp_processor = providers.Singleton(
        Processor,
        metadata_extractor=rp_metadata,
        chunk_reader=rp_chunk_reader
    )
    
    rp_stream_processor = providers.Singleton(
        StreamProcessor,
        metadata_extractor=rp_metadata,
        chunk_reader=rp_chunk_reader
    )
    
    rp_serializer = providers.Singleton(ResultSerializer)
    rp_cache = providers.Singleton(RPCache)
    rp_metrics = providers.Singleton(RPMetricsLogger)
    
    result_processing_service = providers.Singleton(
        ResultProcessingService,
        execution_service=execution_service,
        processor=rp_processor,
        stream_processor=rp_stream_processor,
        serializer=rp_serializer,
        cache=rp_cache,
        metrics_logger=rp_metrics
    )
    
    # Semantic Analysis Engine
    sa_classifier = providers.Singleton(ColumnClassifier)
    sa_quality = providers.Singleton(QualityAnalyzer)
    sa_distribution = providers.Singleton(DistributionAnalyzer)
    sa_outliers = providers.Singleton(OutlierDetector)
    sa_correlation = providers.Singleton(CorrelationAnalyzer)
    
    sa_relationship = providers.Singleton(
        RelationshipDetector,
        correlation_analyzer=sa_correlation
    )
    
    sa_statistics = providers.Singleton(
        StatisticsEngine,
        quality_analyzer=sa_quality,
        distribution_analyzer=sa_distribution,
        outlier_detector=sa_outliers
    )
    
    sa_metadata_builder = providers.Singleton(MetadataBuilder)
    
    sa_analyzer = providers.Singleton(
        SemanticAnalyzer,
        classifier=sa_classifier,
        quality_analyzer=sa_quality,
        distribution_analyzer=sa_distribution,
        outlier_detector=sa_outliers,
        relationship_detector=sa_relationship,
        statistics_engine=sa_statistics,
        metadata_builder=sa_metadata_builder
    )
    
    sa_registry = providers.Singleton(AnalyzerRegistry)
    sa_factory = providers.Singleton(
        AnalyzerFactory,
        registry=sa_registry,
        default_analyzer=sa_analyzer
    )
    
    sa_cache = providers.Singleton(SemanticCache)
    sa_metrics = providers.Singleton(SemanticMetricsCollector)
    
    semantic_analysis_service = providers.Singleton(
        SemanticAnalysisService,
        result_processing_service=result_processing_service,
        analyzer_factory=sa_factory,
        cache=sa_cache,
        metrics=sa_metrics
    )
    
    # Context Builder Engine
    cb_schema_ext = providers.Singleton(SchemaContextExtractor)
    cb_prof_ext = providers.Singleton(ProfilingContextExtractor)
    cb_sem_ext = providers.Singleton(SemanticContextExtractor)
    cb_plan_ext = providers.Singleton(PlanningContextExtractor)
    cb_q_ext = providers.Singleton(QuestionContextExtractor)
    cb_exec_ext = providers.Singleton(ExecutionContextExtractor)
    
    cb_ranking = providers.Singleton(RankingEngine)
    cb_token_provider = providers.Singleton(OpenAITokenProvider)
    cb_token_est = providers.Singleton(TokenEstimator, provider=cb_token_provider)
    cb_compressor = providers.Singleton(ContextCompressor)
    
    cb_optimizer = providers.Singleton(
        ContextOptimizer,
        ranking_engine=cb_ranking,
        token_estimator=cb_token_est,
        compressor=cb_compressor
    )
    
    cb_validator = providers.Singleton(ContextValidator)
    
    cb_builder = providers.Singleton(
        ContextBuilder,
        extractors=providers.List(
            cb_schema_ext, cb_prof_ext, cb_sem_ext, cb_plan_ext, cb_q_ext, cb_exec_ext
        ),
        optimizer=cb_optimizer,
        validator=cb_validator
    )
    
    cb_registry = providers.Singleton(BuilderRegistry)
    cb_factory = providers.Singleton(
        BuilderFactory,
        registry=cb_registry,
        default_builder=cb_builder
    )
    
    cb_cache = providers.Singleton(CBCache)
    cb_metrics = providers.Singleton(ContextMetricsCollector)
    
    context_builder_service = providers.Singleton(
        ContextBuilderService,
        builder_factory=cb_factory,
        cache=cb_cache,
        metrics=cb_metrics
    )
    
    # Dummy clients for LLM providers (to satisfy DI without external packages)
    class DummyClient:
        pass
        
    dummy_client = providers.Singleton(DummyClient)
    
    openai_provider = providers.Singleton(OpenAIProvider, client=dummy_client)
    gemini_provider = providers.Singleton(GeminiProvider, client=dummy_client)
    claude_provider = providers.Singleton(ClaudeProvider, client=dummy_client)
    local_provider = providers.Singleton(LocalLLMProvider, client=dummy_client)
    
    # AI Reasoning & Explanation Engine
    ai_prompt_builder = providers.Singleton(PromptBuilder)
    
    ai_provider_router = providers.Singleton(
        ProviderRouter,
        openai_provider=openai_provider,
        gemini_provider=gemini_provider,
        claude_provider=claude_provider,
        local_provider=local_provider
    )
    
    ai_trace_builder = providers.Singleton(ReasoningTraceBuilder)
    ai_guard = providers.Singleton(HallucinationGuard)
    ai_validator = providers.Singleton(ResponseValidator)
    ai_citation_builder = providers.Singleton(CitationBuilder)
    ai_confidence = providers.Singleton(ConfidenceEngine)
    ai_recommendation = providers.Singleton(RecommendationEngine)
    ai_followup = providers.Singleton(FollowupGenerator)
    ai_explanation = providers.Singleton(ExplanationEngine)
    
    ai_answer_generator = providers.Singleton(
        AnswerGenerator,
        prompt_builder=ai_prompt_builder
    )
    
    ai_reasoning_engine = providers.Singleton(
        ReasoningEngine,
        provider_router=ai_provider_router,
        answer_generator=ai_answer_generator,
        trace_builder=ai_trace_builder,
        guard=ai_guard,
        validator=ai_validator,
        citation_builder=ai_citation_builder,
        confidence_engine=ai_confidence,
        recommendation_engine=ai_recommendation,
        followup_generator=ai_followup,
        explanation_engine=ai_explanation
    )
    
    ai_registry = providers.Singleton(ReasoningEngineRegistry)
    ai_factory = providers.Singleton(
        ReasoningEngineFactory,
        registry=ai_registry,
        default_engine=ai_reasoning_engine
    )
    
    ai_cache = providers.Singleton(ReasoningCache)
    ai_metrics = providers.Singleton(ReasoningMetricsCollector)
    
    ai_reasoning_service = providers.Singleton(
        AIReasoningService,
        context_service=context_builder_service,
        engine_factory=ai_factory,
        cache=ai_cache,
        metrics=ai_metrics
    )
    
    # Conversation Engine
    conv_session_manager = providers.Singleton(SessionManager)
    conv_memory_cache = providers.Singleton(MemoryCache)
    conv_stm = providers.Singleton(ShortTermMemory, memory_cache=conv_memory_cache)
    conv_ltm = providers.Singleton(LongTermMemory, memory_cache=conv_memory_cache)
    conv_compressor = providers.Singleton(HistoryCompressor)
    
    conv_memory_manager = providers.Singleton(
        MemoryManager,
        stm=conv_stm,
        ltm=conv_ltm,
        compressor=conv_compressor
    )
    
    conv_entity_tracker = providers.Singleton(EntityTracker)
    conv_ref_resolver = providers.Singleton(ReferenceResolver)
    conv_intent_resolver = providers.Singleton(IntentResolver)
    conv_context_reuse = providers.Singleton(ContextReuse)
    
    conv_ttl = providers.Singleton(TTLManager)
    
    conv_context_resolver = providers.Singleton(
        ContextResolver,
        entity_tracker=conv_entity_tracker,
        reference_resolver=conv_ref_resolver,
        intent_resolver=conv_intent_resolver,
        context_reuse=conv_context_reuse,
        ttl_manager=conv_ttl
    )
    
    conv_validator = providers.Singleton(ConversationValidator)
    
    conv_manager = providers.Singleton(
        ConversationManager,
        session_manager=conv_session_manager,
        memory_manager=conv_memory_manager,
        context_resolver=conv_context_resolver,
        validator=conv_validator,
        stm=conv_stm,
        ltm=conv_ltm,
        ttl_manager=conv_ttl
    )
    
    conv_registry = providers.Singleton(ConversationManagerRegistry)
    conv_factory = providers.Singleton(
        ConversationManagerFactory,
        registry=conv_registry,
        default_manager=conv_manager
    )
    
    conv_metrics = providers.Singleton(ConversationMetricsCollector)
    
    conversation_service = providers.Singleton(
        ConversationService,
        manager_factory=conv_factory,
        cache=conv_memory_cache,
        metrics=conv_metrics,
        stm=conv_stm,
        ltm=conv_ltm
    )
    
    # Orchestrator Engine
    orch_event_bus = providers.Singleton(EventBus)
    orch_state_machine = providers.Singleton(StateMachine, event_bus=orch_event_bus)
    orch_retry = providers.Singleton(RetryManager)
    orch_timeout = providers.Singleton(TimeoutManager)
    orch_fallback = providers.Singleton(FallbackManager)
    
    orch_decision = providers.Singleton(DecisionEngine)
    orch_clarification = providers.Singleton(ClarificationEngine)
    orch_context_reuse = providers.Singleton(ContextReuseEngine)
    orch_graph = providers.Singleton(ExecutionGraph)
    
    # We map the services directly to the routing engine
    orch_routing = providers.Singleton(
        RoutingEngine,
        services=providers.Dict(
            conversation=conversation_service,
            query_understanding=query_understanding_service,
            execution_planning=execution_planning_service,
            logical_query=logical_query_service,
            sql_rendering=sql_rendering_service,
            sql_validation=sql_validation_service,
            execution=execution_service,
            result_processing=result_processing_service,
            semantic_analysis=semantic_analysis_service,
            context_builder=context_builder_service,
            ai_reasoning=ai_reasoning_service
        )
    )
    
    orch_workflow = providers.Singleton(
        WorkflowEngine,
        routing_engine=orch_routing,
        state_machine=orch_state_machine
    )
    
    orch_pipeline = providers.Singleton(
        Pipeline,
        execution_graph=orch_graph,
        workflow_engine=orch_workflow,
        decision_engine=orch_decision,
        reuse_engine=orch_context_reuse,
        clarification_engine=orch_clarification,
        state_machine=orch_state_machine
    )
    
    orchestrator = providers.Singleton(
        Orchestrator,
        pipeline=orch_pipeline,
        retry_manager=orch_retry,
        fallback_manager=orch_fallback,
        timeout_manager=orch_timeout
    )
    
    orch_registry = providers.Singleton(OrchestratorRegistry)
    orch_factory = providers.Singleton(
        OrchestratorFactory,
        registry=orch_registry,
        default_orchestrator=orchestrator
    )
    
    orch_metrics = providers.Singleton(OrchestratorMetricsCollector)
    
    orchestrator_service = providers.Singleton(
        OrchestratorService,
        orchestrator_factory=orch_factory,
        metrics=orch_metrics
    )
