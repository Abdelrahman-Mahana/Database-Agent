"""Query Templates & Saved Questions Service (P2 Feature).

Enables saving verified parameterized SQL queries and executing them deterministically
with zero LLM overhead and results caching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.sql_service import SQLExecutor
from app.utils.cache import get_cached_results, set_cached_results


@dataclass
class QueryTemplate:
    template_id: str
    title: str
    description: str
    sql_template: str
    parameters: List[str] = field(default_factory=list)  # e.g. ["start_date", "region"]
    default_values: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TemplateService:
    """Manages template persistence, parameter substitution, and instant execution."""

    def __init__(self):
        self._templates: Dict[str, QueryTemplate] = {}
        self.sql_executor = SQLExecutor()

    def register_template(self, template: QueryTemplate) -> None:
        """Register or update a parameterized query template."""
        self._templates[template.template_id] = template

    def get_template(self, template_id: str) -> Optional[QueryTemplate]:
        return self._templates.get(template_id)

    def list_templates(self, tag: Optional[str] = None) -> List[QueryTemplate]:
        if not tag:
            return list(self._templates.values())
        return [t for t in self._templates.values() if tag in t.tags]

    def render_sql(self, template_id: str, params: Dict[str, Any]) -> str:
        """Substitute parameters safely into the template SQL."""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template '{template_id}' not found.")

        final_params = {**template.default_values, **params}
        rendered = template.sql_template

        for param_name in template.parameters:
            if param_name not in final_params:
                raise ValueError(f"Missing required parameter: '{param_name}'")
            val = final_params[param_name]
            # Replace named placeholder :param_name
            if isinstance(val, (int, float)):
                rendered = re.sub(rf":{param_name}\b", str(val), rendered)
            else:
                escaped_val = str(val).replace("'", "''")
                rendered = re.sub(rf":{param_name}\b", f"'{escaped_val}'", rendered)

        return rendered

    def execute_template(
        self,
        template_id: str,
        params: Dict[str, Any],
        db: Session,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Render and execute the template query deterministically with optional caching."""
        rendered_sql = self.render_sql(template_id, params)

        if use_cache:
            cached = get_cached_results(rendered_sql, db_fingerprint=f"template_{template_id}")
            if cached is not None:
                return cached

        rows = self.sql_executor.execute(rendered_sql, db)
        if use_cache and rows:
            set_cached_results(rendered_sql, rows, db_fingerprint=f"template_{template_id}")

        return rows


# Global singleton instance
template_service = TemplateService()
