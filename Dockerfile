FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Bill Buffer" \
      org.opencontainers.image.description="How much should be in your shared bills account right now" \
      org.opencontainers.image.source="https://github.com/ClarkyAU/billbuffer"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BB_DATA=/data \
    BB_PORT=8080

WORKDIR /app
COPY server.py ./
COPY site ./site

# Starts as root only to set up /data, then drops to an unprivileged user.
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/status' % os.environ.get('BB_PORT','8080'), timeout=4)"

CMD ["python", "/app/server.py"]
