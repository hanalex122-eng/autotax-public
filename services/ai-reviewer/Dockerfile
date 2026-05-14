# AutoTax AI Reviewer — küçük servis, ~50 MB image
FROM python:3.11-slim

WORKDIR /app

# Dependency layer (cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY main.py .

# Railway PORT env injection
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
