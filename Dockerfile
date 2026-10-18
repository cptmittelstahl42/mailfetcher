FROM python:3.13-slim

WORKDIR /opt/mailfetcher

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

RUN mkdir -p \
    /opt/mailfetcher/logs \
    /opt/mailfetcher/state \
    /opt/mailfetcher/archive \
    /opt/mailfetcher/queue/pending \
    /opt/mailfetcher/queue/processing \
    /opt/mailfetcher/queue/delivered \
    /opt/mailfetcher/queue/failed

CMD ["python", "/opt/mailfetcher/src/fetcher.py"]
