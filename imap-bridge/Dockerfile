FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Runs as an unprivileged user: this service reads other people's mail and
# holds mailbox credentials, so it gets no more rights than it needs.
RUN useradd --system --no-create-home bridge
USER bridge

ENV PYTHONPATH=/app/src
EXPOSE 8002

CMD ["uvicorn", "imap_bridge.main:app", "--host", "0.0.0.0", "--port", "8002"]
