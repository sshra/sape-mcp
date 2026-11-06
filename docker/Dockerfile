# Образ собирается из опубликованного репозитория — локальные исходники не нужны.
# Сборка: docker build -t sape-mcp https://github.com/sshra/sape-mcp.git#main:docker
# (или из папки docker: docker build -t sape-mcp .)
FROM python:3.12-slim

RUN pip install --no-cache-dir git+https://github.com/sshra/sape-mcp.git

# stdio по умолчанию; для контейнера задайте SAPE_TRANSPORT=streamable-http
ENV SAPE_TRANSPORT=streamable-http \
    SAPE_HOST=0.0.0.0 \
    SAPE_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "sape_mcp"]
