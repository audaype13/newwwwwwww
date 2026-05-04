FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install build dependencies needed for some packages, install runtime deps, then remove build deps to keep image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Try to remove build dependencies after pip install to reduce image size
RUN apt-get purge -y --auto-remove build-essential gcc libffi-dev || true && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Create non-root user and set permissions
RUN groupadd -r app && useradd -r -g app app && chown -R app:app /app
USER app

CMD ["python", "main.py"]