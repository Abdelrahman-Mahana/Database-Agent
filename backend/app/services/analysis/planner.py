"""Analysis Planner: dedicated layer separating analytical decomposition from SQL generation."""
import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import PromptTemplate

from app.services.analysis.investigation_models import QueryTask
from app.services.analysis.models import (
    AnalysisPlan,
    AnalysisTask,
    ComputationType,
    DataRetrievalRequirement,
)
from app.services.analysis.registry import AnalysisStrategyRegistry
from app.agent.semantic.models import AnalysisLevel, AnalysisOperation, QuerySpec
from app.utils.text_processor import AnalysisType, extract_json_text

logger = logging.getLogger(__name__)

ANALYSIS_PLAN_PROMPT_TEMPLATE = """You are the Senior Business & Data Analyst Planner.
Your job is to create a structured Analytical Investigation Plan for the user's question before any SQL is written.

User Question: {question}
Analytical Goal: {analysis_goal}
Analysis Type: {analysis_type}
Operations: {operations}

Available Schema Context:
{schema}

{conversation_history}

Create a structured analytical plan separating:
1. Analytical Tasks (what analytical business questions, drivers, or computations must be resolved).
2. Query Tasks (the concrete SQL data retrieval tasks needed to answer the analytical tasks).

GUIDELINES FOR QUERY TASKS:
- An analytical task may require ONE or MULTIPLE query tasks (e.g. baseline query + category breakdown query + regional breakdown query).
- Only add dependencies in 'depends_on' when a query strictly relies on prior results (e.g. Q2 filters by a time window discovered in Q1).
- Sibling query tasks (e.g. category breakdown vs regional breakdown) should be independent ('depends_on': [] or 'depends_on': ['q_1'] if both need Q1). Do NOT create artificial linear chains.
- 'expected_evidence' should specify the concrete factual evidence the query is expected to establish (e.g. "Category-level revenue change and share of total drop"). If unknown, leave it null.

Return ONLY raw JSON matching this format (no markdown, no explanations):
{{
  "analysis_goal": "{analysis_goal}",
  "analysis_tasks": [
    {{
      "task_id": "task_1",
      "name": "Quantify Revenue Drop",
      "objective": "Confirm and measure the magnitude of revenue decline",
      "operation": "trend",
      "description": "Calculate baseline vs current period revenue and growth rate",
      "priority": 1,
      "depends_on": [],
      "expected_insights": ["Exact drop percentage and timeline"]
    }},
    {{
      "task_id": "task_2",
      "name": "Identify Decline Drivers",
      "objective": "Isolate negative contributing segments",
      "operation": "root_cause",
      "description": "Decompose revenue across product categories and geographic regions",
      "priority": 2,
      "depends_on": ["task_1"],
      "expected_insights": ["Top contributing categories and regions"]
    }}
  ],
  "query_tasks": [
    {{
      "query_id": "q_1",
      "analytical_task_id": "task_1",
      "purpose": "Retrieve monthly revenue trend",
      "sub_question": "What is the monthly revenue for the last 12 months?",
      "required_metrics": ["total_amount"],
      "required_dimensions": ["order_month"],
      "required_filters": [],
      "expected_grain": "monthly",
      "expected_columns": ["order_month", "total_amount"],
      "expected_evidence": "Monthly revenue trajectory and drop magnitude",
      "depends_on": [],
      "priority": 1,
      "can_be_skipped_if_answered": false
    }},
    {{
      "query_id": "q_2",
      "analytical_task_id": "task_2",
      "purpose": "Revenue breakdown by product category during drop period",
      "sub_question": "What is the revenue by product category for the last quarter?",
      "required_metrics": ["total_amount"],
      "required_dimensions": ["category_name"],
      "required_filters": [],
      "expected_grain": "category",
      "expected_columns": ["category_name", "total_amount"],
      "expected_evidence": "Category-level revenue share and decline amount",
      "depends_on": ["q_1"],
      "priority": 2,
      "can_be_skipped_if_answered": false
    }},
    {{
      "query_id": "q_3",
      "analytical_task_id": "task_2",
      "purpose": "Revenue breakdown by geographic region during drop period",
      "sub_question": "What is the revenue by customer country for the last quarter?",
      "required_metrics": ["total_amount"],
      "required_dimensions": ["country"],
      "required_filters": [],
      "expected_grain": "country",
      "expected_columns": ["country", "total_amount"],
      "expected_evidence": "Regional revenue change and contribution to decline",
      "depends_on": ["q_1"],
      "priority": 2,
      "can_be_skipped_if_answered": false
    }}
  ],
  "hypotheses": [],
  "expected_insights": ["Overall volume baseline", "Driver segment breakdown"],
  "requires_multi_step": true
}}

JSON Response:"""


class AnalysisPlanner:
    """Creates a high-level analytical plan before SQL queries are generated.

    Separates analytical reasoning ("what business questions must be answered and what metrics calculated")
    from SQL generation ("how to write SELECT statements with joins and filters").
    """

    def __init__(self, fast_llm=None):
        self.fast_llm = fast_llm
        if fast_llm is not None:
            self.llm_chain = (
                PromptTemplate(
                    input_variables=["question", "analysis_goal", "analysis_type", "operations", "schema", "conversation_history"],
                    template=ANALYSIS_PLAN_PROMPT_TEMPLATE,
                )
                | self.fast_llm
            )
        else:
            self.llm_chain = None

    @classmethod
    def plan(
        cls,
        query_spec: QuerySpec,
        schema_text: str = "",
        conversation_history: str = "",
    ) -> AnalysisPlan:
        """Deterministically create an AnalysisPlan from a QuerySpec."""
        return AnalysisStrategyRegistry.build_plan_for_spec(query_spec)

    async def plan_async(
        self,
        query_spec: QuerySpec,
        schema_text: str = "",
        conversation_history: str = "",
    ) -> AnalysisPlan:
        """Asynchronously create an AnalysisPlan, using LLM if complex exploratory reasoning is needed."""
        # Use deterministic blueprint as default / fallback
        default_plan = AnalysisStrategyRegistry.build_plan_for_spec(query_spec)

        # For simple lookups or metric queries, deterministic strategy is faster and optimal
        if not query_spec.analysis_required or query_spec.analysis_level == AnalysisLevel.RETRIEVAL:
            return default_plan

        if self.llm_chain is None or not schema_text:
            return default_plan

        # For deep exploratory / root-cause insights, invoke LLM to tailor the tasks and sub-questions
        try:
            resp = await self.llm_chain.ainvoke({
                "question": query_spec.raw_question,
                "analysis_goal": query_spec.analysis_goal or query_spec.business_goal or query_spec.raw_question,
                "analysis_type": query_spec.analysis_type.value if hasattr(query_spec.analysis_type, "value") else str(query_spec.analysis_type),
                "operations": [op.value if hasattr(op, "value") else str(op) for op in (query_spec.operations or [])],
                "schema": schema_text[:4000],
                "conversation_history": conversation_history,
            })
            content = resp.content if hasattr(resp, "content") else str(resp)
            data = json.loads(extract_json_text(content))

            raw_tasks = data.get("analysis_tasks") or data.get("tasks", [])
            tasks: List[AnalysisTask] = []
            for i, t in enumerate(raw_tasks):
                op_raw = str(t.get("operation", "aggregate")).lower()
                try:
                    op = AnalysisOperation(op_raw)
                except ValueError:
                    op = AnalysisOperation.AGGREGATE
                comp_raw = str(t.get("computation_type", "")).lower()
                try:
                    comp = ComputationType(comp_raw) if comp_raw else None
                except ValueError:
                    comp = None

                task_id = t.get("task_id", f"task_{i+1}")
                deps = t.get("depends_on", []) or t.get("dependencies", [])

                tasks.append(
                    AnalysisTask(
                        task_id=task_id,
                        name=t.get("name", f"Task {i+1}"),
                        objective=t.get("objective") or t.get("description", ""),
                        operation=op,
                        description=t.get("description", ""),
                        computation_type=comp,
                        priority=t.get("priority", 1),
                        depends_on=list(deps),
                        dependencies=list(deps),
                        expected_insights=t.get("expected_insights", []),
                    )
                )

            raw_qtasks = data.get("query_tasks", [])
            query_tasks: List[QueryTask] = []
            if raw_qtasks:
                for i, q in enumerate(raw_qtasks):
                    q_id = q.get("query_id", f"q_{i+1}")
                    q_deps = q.get("depends_on", [])
                    exp_ev = q.get("expected_evidence")
                    query_tasks.append(
                        QueryTask(
                            query_id=q_id,
                            analytical_task_id=q.get("analytical_task_id"),
                            purpose=q.get("purpose", ""),
                            sub_question=q.get("sub_question", query_spec.raw_question),
                            required_metrics=q.get("required_metrics", query_spec.metrics),
                            required_dimensions=q.get("required_dimensions", query_spec.dimensions),
                            required_filters=q.get("required_filters", query_spec.filters),
                            expected_grain=q.get("expected_grain"),
                            expected_columns=q.get("expected_columns", []),
                            expected_evidence=exp_ev if exp_ev else None,
                            depends_on=list(q_deps),
                            priority=q.get("priority", 1),
                            can_be_skipped_if_answered=q.get("can_be_skipped_if_answered", False),
                        )
                    )
            elif "data_requirements" in data:
                # Fallback if old schema was returned
                raw_reqs = data.get("data_requirements", [])
                for i, r in enumerate(raw_reqs):
                    req_id = r.get("requirement_id", f"req_{i+1}")
                    query_tasks.append(
                        QueryTask(
                            query_id=req_id,
                            analytical_task_id=r.get("analytical_task_id"),
                            purpose=r.get("description", f"Requirement {i+1}"),
                            sub_question=r.get("sub_question", query_spec.raw_question),
                            required_metrics=query_spec.metrics,
                            required_dimensions=query_spec.dimensions,
                            expected_evidence=r.get("expected_evidence"),
                            priority=i + 1,
                        )
                    )

            if tasks or query_tasks:
                return AnalysisPlan(
                    question=query_spec.raw_question,
                    analysis_required=True,
                    analysis_level=query_spec.analysis_level,
                    analysis_type=query_spec.analysis_type,
                    analysis_goal=data.get("analysis_goal", query_spec.analysis_goal or query_spec.raw_question),
                    tasks=tasks,
                    query_tasks=query_tasks,
                    hypotheses=data.get("hypotheses", []),
                    expected_insights=data.get("expected_insights", default_plan.expected_insights),
                    constraints=query_spec.constraints,
                    requires_multi_step=bool(data.get("requires_multi_step", len(query_tasks) > 1)),
                    source="llm_analysis_planner",
                )
        except Exception as e:
            logger.warning("LLM AnalysisPlanner failed, falling back to deterministic registry strategy: %s", e)

        return default_plan

    @classmethod
    def plan_investigation(
        cls,
        query_spec: QuerySpec,
        schema_text: str = "",
        conversation_history: str = "",
    ) -> "InvestigationPlan":
        """Deterministically create a validated InvestigationPlan with AnalysisTasks and QueryTasks."""
        from app.services.analysis.investigation_models import InvestigationMode

        plan = cls.plan(query_spec, schema_text=schema_text, conversation_history=conversation_history)
        mode = derive_investigation_mode(query_spec)
        max_q = 3 if mode == InvestigationMode.DIRECT else (7 if mode in (InvestigationMode.ROOT_CAUSE, InvestigationMode.EXPLORATORY) else 5)
        inv_plan = plan.to_investigation_plan(investigation_mode=mode, max_queries=max_q)
        inv_plan.validate_plan(raise_on_error=False)
        return inv_plan

    async def plan_investigation_async(
        self,
        query_spec: QuerySpec,
        schema_text: str = "",
        conversation_history: str = "",
    ) -> "InvestigationPlan":
        """Asynchronously create a validated InvestigationPlan with AnalysisTasks and QueryTasks."""
        from app.services.analysis.investigation_models import InvestigationMode

        plan = await self.plan_async(query_spec, schema_text=schema_text, conversation_history=conversation_history)
        mode = derive_investigation_mode(query_spec)
        max_q = 3 if mode == InvestigationMode.DIRECT else (7 if mode in (InvestigationMode.ROOT_CAUSE, InvestigationMode.EXPLORATORY) else 5)
        inv_plan = plan.to_investigation_plan(investigation_mode=mode, max_queries=max_q)
        inv_plan.validate_plan(raise_on_error=False)
        return inv_plan


def derive_investigation_mode(query_spec: QuerySpec) -> "InvestigationMode":
    """Map QuerySpec analytical profile into an appropriate InvestigationMode."""
    from app.services.analysis.investigation_models import InvestigationMode

    at = query_spec.analysis_type
    ops = query_spec.operations or []

    if at in (AnalysisType.ROOT_CAUSE, AnalysisType.CORRELATION) or AnalysisOperation.ROOT_CAUSE in ops:
        return InvestigationMode.ROOT_CAUSE
    if at in (AnalysisType.COMPARISON, AnalysisType.SEGMENTATION) or AnalysisOperation.COMPARE in ops:
        return InvestigationMode.COMPARATIVE
    if at == AnalysisType.FORECASTING or AnalysisOperation.FORECAST in ops:
        return InvestigationMode.FORECASTING
    if at in (AnalysisType.DATA_QUALITY, AnalysisType.DISTRIBUTION) or AnalysisOperation.DATA_QUALITY in ops:
        return InvestigationMode.DATA_AUDIT
    if not query_spec.analysis_required or query_spec.analysis_level == AnalysisLevel.RETRIEVAL:
        return InvestigationMode.DIRECT
    return InvestigationMode.EXPLORATORY


