FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    HISTORICAL_DATA_ROOT=/app/backend/data/processed \
    FAIL_ON_DATA_LOAD_ERROR=true

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --home /home/appuser appuser

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY backend/__init__.py backend/run.py ./backend/
COPY backend/app ./backend/app
COPY backend/data/processed ./backend/data/processed

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 5000

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - backend.run:app"]
