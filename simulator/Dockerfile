# S-26: versioned simulator image used identically by local Compose and CI.
FROM python:3.12-slim

ARG OCPP_VERSION
ARG WEBSOCKETS_VERSION

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && python -m pip install --no-cache-dir \
        "ocpp==${OCPP_VERSION}" \
        "websockets==${WEBSOCKETS_VERSION}" \
        "httpx==0.28.1"

COPY simulator ./simulator

RUN useradd --create-home simulator \
    && chown -R simulator:simulator /app

USER simulator
