# syntax=docker/dockerfile:1

## -----------------------------------------------------
## Build stage
FROM dhi.io/python:3-dev AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /app/venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

## -----------------------------------------------------
## Final stage
FROM dhi.io/python:3 AS runtime-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY oracle_usage_bot.py .

# Health check: Verify /tmp/ocm_healthy file exists and was updated within last 2 minutes
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD test -f /tmp/ocm_healthy && test $(find /tmp/ocm_healthy -mmin -2 | wc -l) -eq 1 || exit 1

CMD ["python", "-u", "oracle_usage_bot.py"]