from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    project_name: str = "AI Database Analyst Agent"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    
    # Profiling Settings
    sampling_threshold: int = 100000
    random_sample_size: int = 10000
    max_top_values: int = 10
    entropy_threshold: float = 0.5
    max_concurrent_profiles: int = 5
    
    # Add future settings here (DB credentials, API keys, etc.)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

def get_settings() -> Settings:
    return Settings()
