# Imagen de la tarea de ECS "migrar" (T-031, design.md §2.8). Se construye desde la raíz:
#   docker build -f infra/docker/migrar/Dockerfile -t cc-migrar .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app

RUN pip install --no-cache-dir "alembic>=1.13" "psycopg[binary]>=3.2" "sqlalchemy[asyncio]>=2.0.35" \
      "pydantic>=2.9" "pydantic-settings>=2.5"

COPY services/shared/cc_common ./services/shared/cc_common
# COPY de una carpeta copia su contenido: cada carpeta se copia a su ruta completa.
COPY services/dashboard/alembic.ini ./services/dashboard/alembic.ini
COPY services/dashboard/migrations ./services/dashboard/migrations
COPY services/campos/alembic.ini ./services/campos/alembic.ini
COPY services/campos/migrations ./services/campos/migrations
COPY services/colaboradores/alembic.ini ./services/colaboradores/alembic.ini
COPY services/colaboradores/migrations ./services/colaboradores/migrations
COPY services/whatsapp/alembic.ini ./services/whatsapp/alembic.ini
COPY services/whatsapp/migrations ./services/whatsapp/migrations
COPY services/constancias/alembic.ini ./services/constancias/alembic.ini
COPY services/constancias/migrations ./services/constancias/migrations
COPY services/notificaciones/alembic.ini ./services/notificaciones/alembic.ini
COPY services/notificaciones/migrations ./services/notificaciones/migrations
COPY infra/db ./infra/db
COPY scripts/migrar_todo.py ./scripts/migrar_todo.py

RUN useradd --uid 10001 --no-create-home migrador
USER 10001

# CC_MIGRAR_URL la inyecta la tarea de ECS desde Secrets Manager (nunca en la imagen).
ENTRYPOINT ["python", "scripts/migrar_todo.py"]
