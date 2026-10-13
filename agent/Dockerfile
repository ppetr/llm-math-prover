# Build from the repo root, not this directory - needs builder/ too
# (pyproject.toml's packages.find covers both):
#   docker build -t ai-math-container-agent -f agent/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY builder ./builder
COPY agent ./agent
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "agent.main:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
