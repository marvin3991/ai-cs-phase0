FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY demo ./demo
COPY data ./data
RUN pip install --no-cache-dir ".[deploy]"
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn src.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
