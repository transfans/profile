FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.1.2 && \
    poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --only main --no-root

COPY alembic.ini ./
COPY alembic/ alembic/
COPY app/ app/

CMD ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8002"]
