FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LAB_DATA_DIR=/data PORT=8000 MALLOC_ARENA_MAX=2
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn demo_execution.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
