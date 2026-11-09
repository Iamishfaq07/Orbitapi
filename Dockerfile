FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY orbitapi ./orbitapi
COPY gateway.py service.py main.py ./
EXPOSE 8000 9000
# Default command runs the gateway; the core service overrides it in compose.
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000"]
