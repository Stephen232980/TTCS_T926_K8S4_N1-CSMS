FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-cryptography ca-certificates && rm -rf /var/lib/apt/lists/*
COPY scripts/backup_database.py /opt/s62/backup_database.py
ENV S62_BACKUP_DIR=/backups S62_BACKUP_KEY_FILE=/run/secrets/s62.key PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/s62/backup_database.py"]
CMD ["backup"]
