# Imagen de la tarea de ECS "ops" (T-043, design.md §13.9). Se construye desde la raíz:
#   docker buildx build --platform linux/arm64 -f infra/docker/ops/Dockerfile -t cc-ops .
# La tarea corre en Fargate ARM64.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]>=3.2"
COPY scripts/bootstrap_admin.py ./scripts/bootstrap_admin.py
COPY scripts/asignar_contrasenas.py ./scripts/asignar_contrasenas.py
COPY infra/docker/ops/ops.sh ./ops.sh
RUN sed -i 's/\r$//' ops.sh && chmod 0555 ops.sh && useradd --uid 10001 --no-create-home ops
USER 10001
# La tarea queda en espera: las operaciones se lanzan con ECS Exec (ops.sh ...), de modo que un
# código de invitación se muestra solo en la sesión interactiva y no en los registros.
CMD ["sleep", "3600"]
