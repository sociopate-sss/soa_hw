# ER-диаграмма системы бронирования авиабилетов (3NF)

```mermaid
erDiagram
    %% ===== Flight Service DB =====

    flights {
        bigserial id PK
        varchar_10 flight_number "NOT NULL"
        varchar_100 airline "NOT NULL"
        varchar_3 origin "NOT NULL, IATA code"
        varchar_3 destination "NOT NULL, IATA code"
        timestamptz departure_time "NOT NULL"
        timestamptz arrival_time "NOT NULL"
        int total_seats "NOT NULL, CHECK > 0"
        int available_seats "NOT NULL, CHECK >= 0, CHECK <= total_seats"
        decimal_10_2 price "NOT NULL, CHECK > 0"
        varchar_20 status "NOT NULL, DEFAULT SCHEDULED"
        timestamptz created_at "DEFAULT NOW()"
        timestamptz updated_at "DEFAULT NOW()"
    }

    seat_reservations {
        bigserial id PK
        bigint flight_id FK "NOT NULL, REFERENCES flights(id)"
        varchar_50 booking_id UK "NOT NULL, UNIQUE"
        int seat_count "NOT NULL, CHECK > 0"
        varchar_20 status "NOT NULL, DEFAULT ACTIVE"
        timestamptz created_at "DEFAULT NOW()"
        timestamptz updated_at "DEFAULT NOW()"
    }

    flights ||--o{ seat_reservations : "has reservations"

    %% ===== Booking Service DB =====

    bookings {
        uuid id PK "DEFAULT gen_random_uuid()"
        varchar_100 user_id "NOT NULL"
        bigint flight_id "NOT NULL, ref to Flight Service"
        varchar_200 passenger_name "NOT NULL"
        varchar_200 passenger_email "NOT NULL"
        int seat_count "NOT NULL, CHECK > 0"
        decimal_10_2 total_price "NOT NULL, CHECK > 0"
        varchar_20 status "NOT NULL, DEFAULT CONFIRMED"
        timestamptz created_at "DEFAULT NOW()"
        timestamptz updated_at "DEFAULT NOW()"
    }
```

## Нормализация (3NF)

Все таблицы находятся в третьей нормальной форме:

1. **1NF**: Все атрибуты атомарны, нет повторяющихся групп.
2. **2NF**: Нет частичных зависимостей — все неключевые атрибуты зависят от всего первичного ключа (который во всех таблицах — одноколоночный `id`).
3. **3NF**: Нет транзитивных зависимостей — неключевые атрибуты зависят только от первичного ключа.

## Ограничения целостности

| Ограничение | Таблица | Описание |
|---|---|---|
| `total_seats > 0` | flights | Общее количество мест строго положительно |
| `available_seats >= 0` | flights | Количество доступных мест не может быть отрицательным |
| `available_seats <= total_seats` | flights | Доступных мест не больше общего числа |
| `price > 0` | flights | Цена строго положительна |
| `UNIQUE(flight_number, departure_time::date)` | flights | Уникальность рейса по номеру и дате |
| `seat_count > 0` | seat_reservations | Количество зарезервированных мест положительно |
| `booking_id UNIQUE` | seat_reservations | Одному бронированию — одна резервация |
| `flight_id FK` | seat_reservations | Ссылочная целостность на рейс |
| `seat_count > 0` | bookings | Количество мест положительно |
| `total_price > 0` | bookings | Стоимость положительна |

## Связи между сервисами

- `seat_reservations.booking_id` ↔ `bookings.id` — логическая связь между сервисами (не FK, т.к. разные БД)
- `bookings.flight_id` ↔ `flights.id` — логическая ссылка на рейс (не FK, т.к. разные БД)
