FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# stdio по умолчанию; для контейнера задайте SAPE_TRANSPORT=streamable-http
ENV SAPE_TRANSPORT=streamable-http \
    SAPE_HOST=0.0.0.0 \
    SAPE_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "sape_mcp"]
