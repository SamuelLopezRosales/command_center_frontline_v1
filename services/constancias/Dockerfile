# Imagen del servicio constancias y de `worker-pdf` (ECS Fargate ARM64). Se construye desde la raíz:
#   docker build -f services/constancias/Dockerfile -t cc-constancias .
# WeasyPrint necesita Pango; las fuentes (Liberation Sans) van en la imagen para que el PDF no
# dependa del host (design.md §5.4).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app/services/shared:/app/services/constancias
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" \
      "pydantic-settings>=2.5" "structlog>=24.4" "sqlalchemy[asyncio]>=2.0.35" "asyncpg>=0.30" \
      "httpx>=0.27" "cryptography>=43" "boto3>=1.35" "pyjwt[crypto]>=2.9" "tenacity>=9.0" \
      "weasyprint>=70" "jinja2>=3.1" "segno>=1.6"
COPY services/shared/cc_common ./services/shared/cc_common
COPY services/constancias/cc_constancias ./services/constancias/cc_constancias
RUN useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "cc_constancias.main:crear_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header", "--no-access-log"]
