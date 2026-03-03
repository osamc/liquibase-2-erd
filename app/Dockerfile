# Multi-stage: Python app + Java/Liquibase for running changelogs
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Liquibase (CLI)
ARG LIQUIBASE_VERSION=4.24.0
RUN curl -sL "https://github.com/liquibase/liquibase/releases/download/v${LIQUIBASE_VERSION}/liquibase-${LIQUIBASE_VERSION}.tar.gz" \
    -o /tmp/liquibase.tar.gz \
    && mkdir -p /opt/liquibase \
    && tar -xzf /tmp/liquibase.tar.gz -C /opt/liquibase \
    && rm /tmp/liquibase.tar.gz
ENV PATH="/opt/liquibase:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Create directory for uploaded changelogs
RUN mkdir -p /app/uploads

ENV FLASK_APP=app.py
EXPOSE 5000
CMD ["python", "-u", "app.py"]
