# Imagen para correr las pruebas de PDF (WeasyPrint) en Linux, con las mismas librerías y fuentes
# que la imagen de producción. No se despliega. Uso: .\scripts\probar_pdf.ps1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "fastapi>=0.115" "pydantic>=2.9" "pydantic-settings>=2.5" \
      "structlog>=24.4" "sqlalchemy[asyncio]>=2.0.35" "asyncpg>=0.30" "psycopg[binary]>=3.2" \
      "httpx>=0.27" "cryptography>=43" "boto3>=1.35" "pyjwt[crypto]>=2.9" "tenacity>=9.0" \
      "weasyprint>=70" "jinja2>=3.1" "segno>=1.6" "google-re2>=1.1" "openpyxl>=3.1" \
      "pytest>=8.3" "pytest-asyncio>=0.24" "hypothesis>=6.100" "pypdf" "zxing-cpp" \
      "testcontainers[postgres]>=4.8"
CMD ["python", "-m", "pytest"]
