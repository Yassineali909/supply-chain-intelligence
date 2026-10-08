# One image, two roles (seed + app). Base pinned; see README note on Python version.
FROM python:3.12-slim

# System deps: psycopg2 needs libpq; build tools for any wheels that compile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (layer cache: deps change rarely, code changes often).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the project (datagen package + the agent package).
COPY datagen/ ./datagen/
COPY rc07_vertical_slice/ ./rc07_vertical_slice/

# Default workdir for the agent/UI; seed overrides the command.
WORKDIR /app/rc07_vertical_slice

EXPOSE 8501
