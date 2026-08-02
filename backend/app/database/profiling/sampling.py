from app.database.profiling.interfaces import ISamplingStrategy
from app.config.settings import Settings

class FullScanStrategy(ISamplingStrategy):
    @property
    def name(self) -> str:
        return "full"

class RandomSamplingStrategy(ISamplingStrategy):
    def __init__(self, sample_size: int):
        self.sample_size = sample_size
        
    @property
    def name(self) -> str:
        return "random"

class LimitSamplingStrategy(ISamplingStrategy):
    def __init__(self, sample_size: int):
        self.sample_size = sample_size
        
    @property
    def name(self) -> str:
        return "limit"

class StrategyFactory:
    def __init__(self, settings: Settings):
        self.settings = settings
        
    def get_strategy(self, total_rows: int) -> ISamplingStrategy:
        if total_rows <= self.settings.sampling_threshold:
            return FullScanStrategy()
        return LimitSamplingStrategy(self.settings.random_sample_size)
