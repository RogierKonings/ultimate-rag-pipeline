# vLLM Production Dockerfile
# Serves LLM models with OpenAI-compatible API
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV VLLM_WORKER_MULTIPROC_METHOD=spawn

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create symlinks for python
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python

# Install vLLM and dependencies
RUN pip install --no-cache-dir \
    vllm>=0.4.0 \
    ray>=2.9.0 \
    prometheus-client>=0.19.0 \
    pydantic>=2.5.0 \
    httpx>=0.25.0

# Create non-root user
RUN useradd -m -u 1000 vllm
USER vllm
WORKDIR /app

# Copy scripts
COPY --chown=vllm:vllm scripts/ /app/scripts/
COPY --chown=vllm:vllm config/ /app/config/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python3 /app/scripts/healthcheck.py || exit 1

# Expose port
EXPOSE 8000

# Default command - will be overridden by Kubernetes/docker-compose
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
CMD ["--model", "Qwen/Qwen2.5-7B-Instruct", "--port", "8000"]
