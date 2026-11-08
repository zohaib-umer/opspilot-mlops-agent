FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY agent ./agent
COPY api ./api
COPY training ./training
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home runner
COPY artifacts/work/serving /app/model
USER 10001
ENV MODEL_DIR=/app/model
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
