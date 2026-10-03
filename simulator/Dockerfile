# S-26: versioned simulator image used identically by local Compose and CI.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && python -m pip install --no-cache-dir \
        "ocpp==2.1.0" \
        "websockets==15.0.1" \
        "httpx==0.28.1"

COPY simulator ./simulator

RUN useradd --create-home simulator \
    && chown -R simulator:simulator /app

USER simulator
