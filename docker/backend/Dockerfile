FROM python:3.12-slim

WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/uv.lock ./uv.lock
COPY backend/app ./app
RUN pip install --no-cache-dir uv==0.12.9 && uv sync --frozen --extra eeg
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]
