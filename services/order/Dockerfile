# Build context: repo root (so libs/common can be copied).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY services/order/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/common /opt/libs/common
RUN pip install --no-cache-dir -e /opt/libs/common

COPY services/order/ ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
