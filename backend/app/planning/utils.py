def estimate_complexity(num_steps: int) -> str:
    if num_steps <= 3:
        return "LOW"
    elif num_steps <= 7:
        return "MEDIUM"
    return "HIGH"
