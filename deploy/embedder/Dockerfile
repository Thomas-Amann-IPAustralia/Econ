# The Cloud Run embedding service. Build from the repository root:
#   docker build -f deploy/embedder/Dockerfile -t econ-embedder .
# The model is downloaded at build time at a pinned revision and hash-checked, so a cold start reads it
# from the image instead of the network.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ECON_EMBEDDER_DIR=/models
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install -e ".[embedder]"

# MODEL defaults to embedding.adopted in config/pipeline.yaml.
ARG MODEL=""
RUN python -m econ.embedder fetch-model --model "${MODEL}" --dest /models
# RERANKER defaults to reranking.adopted; with none adopted the image serves /embed only (D-012).
ARG RERANKER=""
ENV ECON_RERANKER_DIR=/reranker
RUN python -m econ.embedder fetch-reranker --model "${RERANKER}" --dest /reranker

RUN useradd --uid 10001 --no-create-home app
USER app
CMD exec uvicorn econ.embedder:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
