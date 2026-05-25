FROM python:3.11-slim

# Cloudflare R2 backup: pg_dump must match server version (Railway uses PostgreSQL 18).
# Default Debian package is postgresql-client-17 -> refuses to dump from PG18 server.
# Install postgresql-client-18 from the official PGDG apt repository instead.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 libzbar-dev \
        tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra \
        tesseract-ocr-tur tesseract-ocr-spa libglib2.0-0 poppler-utils \
        postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "autotax.main:app", "--host", "0.0.0.0", "--port", "8080"]
