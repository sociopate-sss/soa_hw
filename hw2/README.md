# Marketplace API

## Запуск

```bash
sudo docker compose up --build
```

API доступен на `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`

## Зайти внутрь контейнера

```bash
# Контейнер с приложением
sudo docker exec -it marketplace_app bash

# Логи только приложения (следить в реальном времени)                                                                                                                                                                              
sudo docker compose logs -f app    

# Консоль PostgreSQL
sudo docker exec -it marketplace_db psql -U marketplace -d marketplace
```

---

## Тестовые запросы curl

---

### 1. Регистрация продавца (SELLER)

```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "seller1",
    "password": "password123",
    "role": "SELLER"
  }' | python3 -m json.tool
```

---

### 2. Регистрация покупателя (USER)

```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "user1",
    "password": "password123",
    "role": "USER"
  }' | python3 -m json.tool
```

---

### 3. Логин продавца → получить SELLER_TOKEN

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "seller1",
    "password": "password123"
  }' | python3 -m json.tool
```

Скопировать `access_token` из ответа → это `SELLER_TOKEN`.

---

### 4. Логин покупателя → получить USER_TOKEN

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "user1",
    "password": "password123"
  }' | python3 -m json.tool
```

Скопировать `access_token` из ответа → это `USER_TOKEN`.
Скопировать `refresh_token` → пригодится в шаге 12.

---

### 5. Создать товар (от имени SELLER)

```bash
curl -s -X POST http://localhost:8000/products \
  -H "Authorization: Bearer SELLER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Смартфон Galaxy S24",
    "description": "Флагманский смартфон с AMOLED-экраном",
    "price": 79999.99,
    "stock": 50,
    "category": "electronics",
    "status": "ACTIVE"
  }' | python3 -m json.tool
```

Запомнить `id` товара из ответа → это `PRODUCT_ID`.

---

### 6. Создать второй товар

```bash
curl -s -X POST http://localhost:8000/products \
  -H "Authorization: Bearer SELLER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Наушники AirPods Pro",
    "price": 19999.00,
    "stock": 100,
    "category": "accessories",
    "status": "ACTIVE"
  }' | python3 -m json.tool
```

Запомнить `id` → это `PRODUCT_ID_2`.

---

### 7. Список товаров с пагинацией и фильтром

```bash
# Все товары, первая страница
curl -s "http://localhost:8000/products?page=0&size=10" \
  -H "Authorization: Bearer USER_TOKEN" | python3 -m json.tool

# Только ACTIVE в категории electronics
curl -s "http://localhost:8000/products?status=ACTIVE&category=electronics" \
  -H "Authorization: Bearer USER_TOKEN" | python3 -m json.tool
```

---

### 8. Обновить товар (только продавец-владелец)

```bash
curl -s -X PUT http://localhost:8000/products/PRODUCT_ID \
  -H "Authorization: Bearer SELLER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "price": 74999.99,
    "stock": 45,
    "description": "Флагман со скидкой"
  }' | python3 -m json.tool
```

---

### 9. Создать промокод (от имени SELLER)

```bash
curl -s -X POST http://localhost:8000/promo-codes \
  -H "Authorization: Bearer SELLER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "SALE20",
    "discount_type": "PERCENTAGE",
    "discount_value": 20,
    "min_order_amount": 10000,
    "max_uses": 100,
    "valid_from": "2024-01-01T00:00:00Z",
    "valid_until": "2030-12-31T23:59:59Z"
  }' | python3 -m json.tool
```

---

### 10. Создать заказ (от имени USER, с промокодом)

```bash
curl -s -X POST http://localhost:8000/orders \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"product_id": PRODUCT_ID, "quantity": 1},
      {"product_id": PRODUCT_ID_2, "quantity": 2}
    ],
    "promo_code": "SALE20"
  }' | python3 -m json.tool
```

Запомнить `id` заказа → это `ORDER_ID`.

---

### 11. Получить заказ по ID

```bash
curl -s http://localhost:8000/orders/ORDER_ID \
  -H "Authorization: Bearer USER_TOKEN" | python3 -m json.tool
```

---

### 12. Обновить заказ (только в статусе CREATED)

```bash
curl -s -X PUT http://localhost:8000/orders/ORDER_ID \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"product_id": PRODUCT_ID, "quantity": 2}
    ]
  }' | python3 -m json.tool
```

---

### 13. Отменить заказ

```bash
curl -s -X POST http://localhost:8000/orders/ORDER_ID/cancel \
  -H "Authorization: Bearer USER_TOKEN" | python3 -m json.tool
```

---

### 14. Обновить access token через refresh token

```bash
curl -s -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "REFRESH_TOKEN_FROM_STEP_4"
  }' | python3 -m json.tool
```

---

### 15. Мягкое удаление товара (перевод в ARCHIVED)

```bash
curl -s -X DELETE http://localhost:8000/products/PRODUCT_ID_2 \
  -H "Authorization: Bearer SELLER_TOKEN" | python3 -m json.tool
```

---

## Граничные случаи (для демонстрации ошибок)

### Создать заказ с несуществующим товаром → PRODUCT_NOT_FOUND

```bash
curl -s -X POST http://localhost:8000/orders \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": 99999, "quantity": 1}]}' | python3 -m json.tool
```

### Создать заказ с товаром в статусе ARCHIVED → PRODUCT_INACTIVE

```bash
curl -s -X POST http://localhost:8000/orders \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": PRODUCT_ID_2, "quantity": 1}]}' | python3 -m json.tool
```

### Создать два заказа подряд → ORDER_HAS_ACTIVE (создать первый, потом сразу второй)

```bash
curl -s -X POST http://localhost:8000/orders \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": PRODUCT_ID, "quantity": 1}]}' | python3 -m json.tool
```

### Невалидные данные → VALIDATION_ERROR

```bash
curl -s -X POST http://localhost:8000/products \
  -H "Authorization: Bearer SELLER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "", "price": -100, "stock": -1, "category": "", "status": "ACTIVE"}' | python3 -m json.tool
```

### USER пытается создать товар → ACCESS_DENIED

```bash
curl -s -X POST http://localhost:8000/products \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Тест", "price": 100, "stock": 1, "category": "test", "status": "ACTIVE"}' | python3 -m json.tool
```

### Запрос без токена → TOKEN_INVALID

```bash
curl -s http://localhost:8000/products | python3 -m json.tool
```

---

## Просмотр данных в PostgreSQL

```bash
sudo docker exec -it marketplace_db psql -U marketplace -d marketplace
```

```sql
-- Таблицы
\dt

-- Пользователи
SELECT id, username, role, created_at FROM users;

-- Товары с индексом по status
SELECT id, name, price, stock, status, seller_id FROM products;

-- Заказы
SELECT id, user_id, status, total_amount, discount_amount FROM orders;

-- Позиции заказа (снапшот цен)
SELECT * FROM order_items;

-- Промокоды
SELECT code, discount_type, discount_value, current_uses, max_uses, active FROM promo_codes;

-- История операций (rate limiting)
SELECT * FROM user_operations ORDER BY created_at DESC;

-- Текущая версия миграций
SELECT * FROM alembic_version;
```
