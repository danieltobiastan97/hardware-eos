FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies first (layer cache-friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY classes.py prompt.py webpage.py prompt.txt ./
COPY templates/ templates/

# uploads/ is created at runtime by the app; no need to COPY it
RUN mkdir -p uploads

# keys.json must be mounted at runtime — do not bake credentials into the image
# docker run -v /path/to/keys.json:/app/keys.json ...

EXPOSE 5000

ENV APP_SECRET_KEY=change-this-secret-key
ENV APP_ADMIN_PASSWORD=changeme

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "webpage:app"]
