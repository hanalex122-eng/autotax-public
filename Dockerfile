FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 libzbar-dev \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra \
    tesseract-ocr-tur tesseract-ocr-spa libglib2.0-0 poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "autotax.main:app", "--host", "0.0.0.0", "--port", "8080"]
