# M0: single-stage image for the walking skeleton. A multi-stage,
# non-root, distroless-style build is a Phase D (M13) deployment-hardening
# concern (architecture §17.5) — not worth the complexity before there is
# more than one endpoint to serve.
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY README.md ./

RUN pip install --no-cache-dir .

ENV GOV_PLATFORM_EVIDENCE_DB_PATH=/app/data/evidence.db
EXPOSE 8000

CMD ["uvicorn", "gov_platform.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
