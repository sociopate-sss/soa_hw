# Flight Booking System — примеры использования

## Запуск

```bash
cd hw3
docker compose up -d --build
```

Проверить статус контейнеров:

```bash
docker compose ps
```

Проверить логи:

```bash
docker compose logs flight-service --tail 20
docker compose logs booking-service --tail 20
```

---

## Поиск рейсов

```bash
# По маршруту
curl -s "http://localhost:8080/flights?origin=SVO&destination=LED" | python3 -m json.tool

# По маршруту и дате
curl -s "http://localhost:8080/flights?origin=SVO&destination=AER&date=2026-04-02" | python3 -m json.tool

# Конкретный рейс по ID
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool
```

---

## Бронирование

### Создание

```bash
curl -s -X POST "http://localhost:8080/bookings" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "flight_id": 1,
    "passenger_name": "Иван Иванов",
    "passenger_email": "ivan@example.com",
    "seat_count": 2
  }' | python3 -m json.tool
```

В ответе будет `id` — это ID бронирования.

### Проверка

```bash
# Получить бронирование
curl -s "http://localhost:8080/bookings/BOOKING_ID" | python3 -m json.tool

# Убедиться что места уменьшились (available_seats: 178)
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool

# Все бронирования пользователя
curl -s "http://localhost:8080/bookings?user_id=user1" | python3 -m json.tool
```

### Отмена

```bash
curl -s -X POST "http://localhost:8080/bookings/BOOKING_ID/cancel" | python3 -m json.tool

# Места вернулись (available_seats: 180)
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool
```

### Обработка ошибок

```bash
# Несуществующий рейс → 404
curl -s "http://localhost:8080/flights/999" | python3 -m json.tool

# Повторная отмена → 400
curl -s -X POST "http://localhost:8080/bookings/BOOKING_ID/cancel" | python3 -m json.tool
```

---

## Кеширование (Cache-Aside + Redis)

```bash
# Первый запрос — cache MISS, данные из PostgreSQL
curl -s "http://localhost:8080/flights/1" > /dev/null

# Второй запрос — cache HIT, данные из Redis
curl -s "http://localhost:8080/flights/1" > /dev/null

# В логах видно HIT/MISS
docker compose logs flight-service --tail 10 | grep -i cache
```

Инвалидация при бронировании:

```bash
# Положить в кеш
curl -s "http://localhost:8080/flights/1" > /dev/null

# Создать бронирование — кеш инвалидируется
curl -s -X POST "http://localhost:8080/bookings" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user2","flight_id":1,"passenger_name":"Test","passenger_email":"t@t.com","seat_count":1}' > /dev/null

# Следующий запрос — снова MISS (кеш был удалён)
curl -s "http://localhost:8080/flights/1" > /dev/null

docker compose logs flight-service --tail 15 | grep -i cache
```

---

## Redis Sentinel

```bash
# Проверить что sentinel видит мастер
docker compose exec redis-sentinel-1 redis-cli -p 26379 sentinel master mymaster

# Узнать адрес текущего мастера
docker compose exec redis-sentinel-1 redis-cli -p 26379 sentinel get-master-addr-by-name mymaster
```

---

## Retry и Circuit Breaker

Эмуляция недоступности Flight Service:

```bash
# Остановить flight-service
docker compose stop flight-service

# Запрос — booking-service сделает 3 retry с exponential backoff, затем вернёт 503
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool

# Retry в логах
docker compose logs booking-service --tail 20 | grep -i retry
```

Circuit breaker срабатывает после нескольких ошибок:

```bash
# Сделать несколько запросов подряд
for i in $(seq 1 6); do
  echo "--- Request $i ---"
  curl -s "http://localhost:8080/flights/1" | python3 -m json.tool
done

# Переходы состояний в логах
docker compose logs booking-service --tail 30 | grep -i circuit

# В состоянии OPEN запросы мгновенно возвращают 503
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool
```

Восстановление:

```bash
# Вернуть flight-service
docker compose start flight-service

# Подождать recovery_timeout (30 сек)
sleep 35

# Запрос пройдёт: OPEN → HALF_OPEN → пробный запрос → CLOSED
curl -s "http://localhost:8080/flights/1" | python3 -m json.tool

docker compose logs booking-service --tail 10 | grep -i circuit
```

---

## Остановка

```bash
docker compose down -v
```
