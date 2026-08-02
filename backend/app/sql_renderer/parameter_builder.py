from typing import Any, List
from app.sql_renderer.models import SQLParameter

class ParameterBuilder:
    def __init__(self, style: str = "qmark"):
        self.style = style.lower()
        self.params: List[SQLParameter] = []
        self.counter = 1
        
    def add_parameter(self, value: Any, type_hint: str = "UNKNOWN") -> str:
        param_name = f"p{self.counter}"
        
        param = SQLParameter(
            name=param_name,
            value=value,
            type_name=type(value).__name__ if type_hint == "UNKNOWN" else type_hint,
            position=self.counter
        )
        self.params.append(param)
        
        if self.style == 'qmark':
            marker = "?"
        elif self.style == 'numeric':
            marker = f"${self.counter}"
        elif self.style == 'named':
            marker = f":{param_name}"
        elif self.style == 'at_named':
            marker = f"@{param_name}"
        else:
            marker = "?"
            
        self.counter += 1
        return marker
