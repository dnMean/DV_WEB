FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "pytest>=8,<9" "httpx>=0.27,<1"
WORKDIR /e2e
COPY . .
CMD ["pytest", "-q", "-p", "no:cacheprovider"]
