FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app.py core.py compliance.py line_api.py ./
COPY data ./data
COPY static ./static
RUN python -c "import app; app.create_app(); print('import OK')"

# Single worker: state is in memory.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 -b 0.0.0.0:${PORT:-8000} 'app:create_app(start_scheduler=True)'"]
