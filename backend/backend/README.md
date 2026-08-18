# AI Database Analyst Agent - Core Foundation

This is the production-ready core foundation for the AI Database Analyst Agent.
It provides a modular, extensible architecture designed for enterprise readiness, without any embedded business logic, SQL generation, or AI agents.

## Architecture Highlights

1. **Framework**: FastAPI (Python 3.12)
2. **Package Management**: `uv`
3. **Dependency Injection**: `dependency-injector` for declarative containerization.
4. **Configuration**: `pydantic-settings` for robust environment variable parsing.
5. **Logging**: `structlog` for structured JSON logging with request IDs and timing metrics.
6. **Plugin System**: A dynamic plugin system to support various databases through a unified `DatabaseConnector` interface.

## Project Structure

```text
backend/
├── app/
│   ├── api/          # API routers and endpoints
│   ├── config/       # Pydantic settings and configuration
│   ├── core/         # DI containers and core initialization
│   ├── database/     # DB connections (future)
│   ├── dependencies/ # FastAPI dependency injection helpers
│   ├── exceptions/   # Centralized exception handlers
│   ├── middleware/   # Custom middlewares (logging, timing)
│   ├── models/       # ORM models (future)
│   ├── plugins/      # Database plugin system and connectors
│   ├── schemas/      # Pydantic schemas for request/response validation
│   ├── services/     # Business logic layer (future)
│   ├── telemetry/    # Logging setup and metrics
│   └── utils/        # Shared utilities
├── Dockerfile        # Production Docker configuration
├── docker-compose.yml# Local development with Docker
├── Makefile          # Common developer tasks
└── pyproject.toml    # Project dependencies managed by uv
```

## Running the Application

### Using uv (Locally)
```bash
make install
make run
```

### Using Docker
```bash
make docker-compose-up
```

## Plugins
The application automatically discovers and registers database plugins from `app.plugins.connectors`. Any new database connector that inherits from `DatabaseConnector` and is placed in this directory will be loaded on startup.
