import structlog

logger = structlog.get_logger(__name__)

class MetricsCollector:
    def record_execution(self, dialect: str, duration: float, success: bool,
                         pool_wait_time: float = 0.0,
                         connection_reused: bool = False,
                         network_time: float = 0.0):
        logger.info("execution_metrics", 
                    dialect=dialect, 
                    duration=duration, 
                    success=success,
                    pool_wait_time=pool_wait_time,
                    connection_reused=connection_reused,
                    network_time=network_time)
