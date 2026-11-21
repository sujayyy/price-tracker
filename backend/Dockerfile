FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend

COPY . /srv/backend
# Model provider extra, matching AGENT_MODEL's "provider:" prefix. Compose passes AI_PROVIDER
# from infra/.env.
ARG AI_PROVIDER=google
RUN pip install "/srv/backend[${AI_PROVIDER}]"

EXPOSE 8000
# Migrations + checkpointer setup are idempotent, so running them on every start is safe.
CMD ["sh", "-c", "python -m app.cli init-db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
