FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create symlink so "from orchestrator.xxx" imports resolve to /app/xxx
RUN mkdir -p /packages && ln -s /app /packages/orchestrator

# Add shared modules and orchestrator namespace to path
ENV PYTHONPATH=/app:/app/shared:/packages

EXPOSE 8003

CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003", "--reload"]
