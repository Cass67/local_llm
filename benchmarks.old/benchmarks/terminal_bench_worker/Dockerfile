# Terminal-Bench Worker Container
FROM python:3.12-slim-bookworm

# Install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy the benchmark service code
COPY terminal_bench_worker.py ./
COPY benchmarks/ ./benchmarks/

EXPOSE 3101

ENV BENCHMARK_PORT=3101

CMD ["python", "terminal_bench_worker.py"]
