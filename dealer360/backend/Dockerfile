FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV DEALER360_DATA=/data
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
