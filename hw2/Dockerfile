FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Копируем исходники
COPY . .

# Генерация, миграции и запуск — всё при старте контейнера,
# чтобы не конфликтовать с volume-монтированием исходников
CMD ["sh", "-c", "\
    datamodel-codegen \
        --input api/openapi.yaml \
        --input-file-type openapi \
        --output generated/models.py \
        --output-model-type pydantic_v2.BaseModel \
        --use-annotated \
        --strict-nullable \
        --field-constraints \
        --use-double-quotes \
    && touch generated/__init__.py \
    && alembic upgrade head \
    && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
