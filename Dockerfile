FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY mock_catalog ./mock_catalog
COPY ml_workspace/__init__.py ./ml_workspace/
COPY ml_workspace/ml_api ./ml_workspace/ml_api
COPY ml_workspace/taxonomy ./ml_workspace/taxonomy
COPY ml_workspace/model ./ml_workspace/model
COPY ml_workspace/catalog_matching ./ml_workspace/catalog_matching
COPY certs ./certs

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
