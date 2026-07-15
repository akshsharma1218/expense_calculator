FROM python:3.13-slim AS builder

# Build stage - compile dependencies
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --user --no-cache-dir -r requirements-prod.txt

# Final stage - minimal runtime image
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH

WORKDIR /app

# Install only runtime dependencies (no gcc, no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/logs /app/staticfiles && \
    chown -R appuser:appuser /app

# Copy dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check (optimized for k3s)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8000), timeout=5)" || exit 1

# Production startup with migrations and static collection
CMD ["sh", "-c", "\
    python manage.py migrate --noinput && \
    python manage.py createsuperuser --noinput || true && \
    python manage.py create_categories --noinput || true && \
    python manage.py collectstatic --noinput --clear && \
    gunicorn expense_calculator.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 4 \
        --worker-class sync \
        --max-requests 1000 \
        --max-requests-jitter 100 \
        --timeout 60 \
        --graceful-timeout 30 \
        --keep-alive 5 \
        --access-logfile - \
        --error-logfile - \
        --log-level info \
    "]
