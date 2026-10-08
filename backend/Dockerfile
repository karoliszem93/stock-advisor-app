FROM python:3.12-slim

# git is needed to commit + push the data repo
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Paths inside the container — host folders are bind-mounted here (see docker-compose.yml).
ENV SQLITE_PATH=/app/data/stock-advisor.db \
    DATA_REPO_PATH=/data-repo \
    GITHUB_TOKEN_FILE=/run/secrets/github_token \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
