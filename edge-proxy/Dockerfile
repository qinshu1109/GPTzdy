FROM python:3.12-slim

RUN pip install --no-cache-dir aiohttp==3.12.0

WORKDIR /app
COPY proxy.py /app/proxy.py

ENV LISTEN_HOST=0.0.0.0
ENV LISTEN_PORT=50002
ENV UPSTREAM=http://chatgpt-mirror:50003

CMD ["python", "/app/proxy.py"]
