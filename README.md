# Automobile_Prototype

Automobile Prototype Backend Starter: Built with standard module and database conventions.

## Structure

```text
apps/
  main.py
  app_logging/
    logging_config.py
    logging_context.py
    logging_filter.py
    logging_formatter.py
    logging_middleware.py
    logging_queue.py
    logging_setup.py
  settings/
    config.py
    databases/
      base_class.py
      base.py
      postgres_db_connection.py
  shared/
    exceptions.py
    logging_config.py
.env.example
```

`main.py` owns app creation, CORS, exception handlers, request logging, local media
mounting, resource lifecycle, and router registration. Settings select `.env_dev` by default; set the process variable
`ENVIRONMENT=staging` or `ENVIRONMENT=production` to select `.env_stag` or `.env_prod`.
Real environment files are ignored by Git. Configure this service's database URL;
the scaffold does not share another application's credentials automatically.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi "uvicorn[standard]" SQLAlchemy asyncpg pydantic-settings python-dotenv
Copy-Item .env.example .env_dev
uvicorn apps.main:app --reload --port 6566
```

Update `DATABASE_URL` in your local configuration for the intended PostgreSQL database.
Dependencies are installed and frozen manually by the team; no requirements lockfile
or migrations have been generated in this scaffold. `psycopg2-binary` and `alembic` are
needed when you choose to set up synchronous migrations later.

Health: `http://127.0.0.1:6566/health`

Swagger: `http://127.0.0.1:6566/docs`

The health endpoint is liveness only. Startup does not connect to PostgreSQL, create
tables, or apply migrations. `APP_ROOT_PATH` is a reverse-proxy prefix, not a route
prefix. Its default is `/api`, matching parent portal; leave it empty in your local
configuration for direct local Swagger requests without a reverse proxy.

## Adding Feature Modules

Use `apps/<feature>_module/` with `__init__.py`, `<feature>_models.py`,
`<feature>_schemas.py`, `<feature>_services.py`, and `<feature>_routers.py`.

- Import ORM `Base` from `apps.settings.databases.base_class`.
- Import each new model module in `apps/settings/databases/base.py` so its tables
  register on `target_metadata` when migration tooling is configured.
- Import `get_db` from `apps.settings.databases.postgres_db_connection` in routers.
- Routers own transactions using `async with db.begin()`; services validate, query,
  and flush, and do not commit or roll back independently.
- Raise the shared `AppError` subclasses for business errors. Responses use the
  existing `message`, `data`, and `code` envelope.
- Register each feature router in `apps/main.py` using `app.include_router(...)`.

Authentication, subscriptions, Redis, and feature-specific modules are left for
their respective stories. The starter has no protected business endpoints.

## Common Settings

Core, PostgreSQL, media/S3, optional AWS credentials, CORS, and logging settings use
the same names, defaults, and helpers as parent portal. The school service retains
its own app title, logging service name, and default database name.

Local media is mounted at `PUBLIC_MEDIA_PREFIX`, matching parent portal. Upload and
AWS services are not implemented. Cognito, OTP, payment, and Redis settings are not
included.

## Logging Conventions

The `app_logging` package matches parent portal: a bounded non-blocking queue,
console/JSON formatters, request IDs and trace context, sensitive-field redaction,
slow-request logging, and bounded shutdown flushing. `LOG_FORMAT=console` produces
readable local logs; use `LOG_FORMAT=json` for structured deployment logs.
Request/response bodies are not read by the logging middleware.

Use `logger = logging.getLogger(__name__)` in new modules and structured metadata:

```python
logger.info(
    "Operation completed",
    extra={"event": "OPERATION_COMPLETED", "category": "SYSTEM"},
)
```

`apps.shared.logging_config.setup_logger` is retained for compatibility with the
existing module pattern. Configure logging once in `main.py`; the lifespan starts
the listener before startup logs and stops it after database shutdown. No additional
logging dependency is required beyond the packages in Local Setup.
