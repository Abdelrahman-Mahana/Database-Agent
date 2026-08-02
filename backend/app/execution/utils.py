# Utility functions for execution engine
import uuid

def generate_execution_id() -> str:
    return str(uuid.uuid4())
