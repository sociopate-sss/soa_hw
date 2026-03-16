"""
Flight Service — gRPC server for flight and seat reservation management.

Features:
- SearchFlights, GetFlight, ReserveSeats, ReleaseReservation
- PostgreSQL with SELECT FOR UPDATE for transactional integrity
- Redis Sentinel caching (Cache-Aside) with TTL and invalidation
- API Key authentication interceptor
- Idempotent ReserveSeats via booking_id uniqueness
"""

import os
import sys
import time
import json
import logging
from concurrent import futures
from datetime import datetime, timezone
from decimal import Decimal

import grpc
import psycopg2
import psycopg2.extras
from redis.sentinel import Sentinel as RedisSentinel
import redis

from google.protobuf.timestamp_pb2 import Timestamp

import flight_pb2
import flight_pb2_grpc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("flight-service")


# ─────────────────────────── Database ───────────────────────────


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "flight_db"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "postgres"),
    )


def run_migrations():
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
    """
    )

    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    applied = {row[0] for row in cur.fetchall()}

    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if os.path.exists(migrations_dir):
        files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
        for f in files:
            version = int(f.split("_")[0])
            if version not in applied:
                logger.info("Applying migration %s", f)
                with open(os.path.join(migrations_dir, f)) as fh:
                    cur.execute(fh.read())
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                )
                logger.info("Migration %s applied", f)

    cur.close()
    conn.close()


# ─────────────────────────── Redis Cache ────────────────────────


class RedisCache:
    """Cache-Aside implementation backed by Redis Sentinel."""

    def __init__(self):
        self.default_ttl = int(os.environ.get("REDIS_TTL", "300"))  # 5 min
        sentinel_hosts_str = os.environ.get("REDIS_SENTINEL_HOSTS", "")
        master_name = os.environ.get("REDIS_MASTER_NAME", "mymaster")

        if sentinel_hosts_str:
            sentinels = []
            for h in sentinel_hosts_str.split(","):
                host, port = h.strip().split(":")
                sentinels.append((host, int(port)))
            self._sentinel = RedisSentinel(sentinels, socket_timeout=3)
            self._master_name = master_name
            self._standalone = None
            logger.info("Redis Sentinel configured: sentinels=%s master=%s", sentinels, master_name)
        else:
            self._sentinel = None
            self._standalone = redis.Redis(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                decode_responses=True,
                socket_timeout=3,
            )
            logger.info("Redis standalone configured")

    @property
    def _master(self):
        if self._sentinel:
            return self._sentinel.master_for(
                self._master_name,
                redis_class=redis.Redis,
                decode_responses=True,
                socket_timeout=3,
            )
        return self._standalone

    # --- public API ---

    def get(self, key: str):
        try:
            value = self._master.get(key)
            if value is not None:
                logger.info("Cache HIT: %s", key)
                return json.loads(value)
            logger.info("Cache MISS: %s", key)
            return None
        except Exception as exc:
            logger.warning("Cache GET error for %s: %s", key, exc)
            return None

    def set(self, key: str, value, ttl: int | None = None):
        try:
            self._master.setex(key, ttl or self.default_ttl, json.dumps(value, default=str))
        except Exception as exc:
            logger.warning("Cache SET error for %s: %s", key, exc)

    def delete(self, key: str):
        try:
            self._master.delete(key)
        except Exception as exc:
            logger.warning("Cache DELETE error for %s: %s", key, exc)

    def delete_pattern(self, pattern: str):
        try:
            master = self._master
            cursor = 0
            while True:
                cursor, keys = master.scan(cursor, match=pattern)
                if keys:
                    master.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("Cache DELETE PATTERN error for %s: %s", pattern, exc)


cache = RedisCache()


# ─────────────────────── Auth Interceptor ───────────────────────


class _AbortHandler(grpc.RpcMethodHandler):
    """Immediately returns UNAUTHENTICATED."""

    def __init__(self):
        self.request_streaming = False
        self.response_streaming = False
        self.request_deserializer = None
        self.response_serializer = None
        self.unary_unary = self._abort
        self.unary_stream = None
        self.stream_unary = None
        self.stream_stream = None

    @staticmethod
    def _abort(request, context):
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing API key")


class AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._abort_handler = _AbortHandler()

    def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata)
        if metadata.get("x-api-key") != self._api_key:
            return self._abort_handler
        return continuation(handler_call_details)


# ─────────────────────── Helpers ────────────────────────────────


def _flight_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "flight_number": row["flight_number"],
        "airline": row["airline"],
        "origin": row["origin"],
        "destination": row["destination"],
        "departure_time": row["departure_time"].isoformat(),
        "arrival_time": row["arrival_time"].isoformat(),
        "departure_date": row["departure_date"].isoformat(),
        "total_seats": row["total_seats"],
        "available_seats": row["available_seats"],
        "price": str(row["price"]),
        "status": row["status"],
    }


def _dict_to_flight_pb(d) -> flight_pb2.Flight:
    flight = flight_pb2.Flight(
        id=d["id"],
        flight_number=d["flight_number"],
        airline=d["airline"],
        origin=d["origin"],
        destination=d["destination"],
        total_seats=d["total_seats"],
        available_seats=d["available_seats"],
        price=float(d["price"]),
        status=flight_pb2.FlightStatus.Value(d["status"]),
    )

    dep = (
        datetime.fromisoformat(d["departure_time"])
        if isinstance(d["departure_time"], str)
        else d["departure_time"]
    )
    arr = (
        datetime.fromisoformat(d["arrival_time"])
        if isinstance(d["arrival_time"], str)
        else d["arrival_time"]
    )

    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)
    if arr.tzinfo is None:
        arr = arr.replace(tzinfo=timezone.utc)

    flight.departure_time.FromDatetime(dep)
    flight.arrival_time.FromDatetime(arr)
    return flight


# ─────────────────── gRPC Service Implementation ───────────────


class FlightServiceServicer(flight_pb2_grpc.FlightServiceServicer):

    # ── SearchFlights ──────────────────────────────────────────

    def SearchFlights(self, request, context):
        origin = request.origin.strip().upper()
        destination = request.destination.strip().upper()

        if not origin or not destination:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "origin and destination are required",
            )
            return flight_pb2.SearchFlightsResponse()

        has_date = request.HasField("date")
        date_str = None
        if has_date:
            dt = request.date.ToDatetime()
            date_str = dt.strftime("%Y-%m-%d")

        # --- Cache-Aside: check cache ---
        cache_key = f"search:{origin}:{destination}:{date_str or 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            resp = flight_pb2.SearchFlightsResponse()
            for d in cached:
                resp.flights.append(_dict_to_flight_pb(d))
            return resp

        # --- DB query ---
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if date_str:
            cur.execute(
                """
                SELECT * FROM flights
                WHERE origin = %s AND destination = %s
                  AND departure_date = %s
                  AND status = 'SCHEDULED'
                ORDER BY departure_time
                """,
                (origin, destination, date_str),
            )
        else:
            cur.execute(
                """
                SELECT * FROM flights
                WHERE origin = %s AND destination = %s
                  AND status = 'SCHEDULED'
                ORDER BY departure_time
                """,
                (origin, destination),
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        flights_data = [_flight_row_to_dict(r) for r in rows]
        cache.set(cache_key, flights_data)

        resp = flight_pb2.SearchFlightsResponse()
        for d in flights_data:
            resp.flights.append(_dict_to_flight_pb(d))
        return resp

    # ── GetFlight ──────────────────────────────────────────────

    def GetFlight(self, request, context):
        flight_id = request.id

        # --- Cache-Aside: check cache ---
        cache_key = f"flight:{flight_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return flight_pb2.GetFlightResponse(flight=_dict_to_flight_pb(cached))

        # --- DB query ---
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM flights WHERE id = %s", (flight_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Flight {flight_id} not found")
            return flight_pb2.GetFlightResponse()

        flight_data = _flight_row_to_dict(row)
        cache.set(cache_key, flight_data)
        return flight_pb2.GetFlightResponse(flight=_dict_to_flight_pb(flight_data))

    # ── ReserveSeats ───────────────────────────────────────────

    def ReserveSeats(self, request, context):
        flight_id = request.flight_id
        seat_count = request.seat_count
        booking_id = request.booking_id

        if seat_count <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "seat_count must be positive")
            return flight_pb2.ReserveSeatsResponse()

        conn = get_db_connection()
        try:
            conn.autocommit = False
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # ── Idempotency: return existing reservation if booking_id matches ──
            cur.execute(
                "SELECT id, status FROM seat_reservations WHERE booking_id = %s",
                (booking_id,),
            )
            existing = cur.fetchone()
            if existing:
                conn.rollback()
                logger.info(
                    "Idempotent ReserveSeats: booking_id=%s already has reservation %s",
                    booking_id,
                    existing["id"],
                )
                return flight_pb2.ReserveSeatsResponse(
                    reservation_id=existing["id"],
                    status=flight_pb2.ReservationStatus.Value(existing["status"]),
                )

            # ── SELECT FOR UPDATE: prevent race conditions ──
            cur.execute("SELECT * FROM flights WHERE id = %s FOR UPDATE", (flight_id,))
            flight = cur.fetchone()

            if not flight:
                conn.rollback()
                context.abort(grpc.StatusCode.NOT_FOUND, f"Flight {flight_id} not found")
                return flight_pb2.ReserveSeatsResponse()

            if flight["available_seats"] < seat_count:
                conn.rollback()
                context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    f"Not enough seats: available={flight['available_seats']}, requested={seat_count}",
                )
                return flight_pb2.ReserveSeatsResponse()

            # ── Atomic: decrement seats + create reservation ──
            cur.execute(
                """
                UPDATE flights
                SET available_seats = available_seats - %s, updated_at = NOW()
                WHERE id = %s
                """,
                (seat_count, flight_id),
            )
            cur.execute(
                """
                INSERT INTO seat_reservations (flight_id, booking_id, seat_count, status)
                VALUES (%s, %s, %s, 'ACTIVE')
                RETURNING id, status
                """,
                (flight_id, booking_id, seat_count),
            )
            reservation = cur.fetchone()
            conn.commit()

            # ── Invalidate cache ──
            cache.delete(f"flight:{flight_id}")
            cache.delete_pattern("search:*")

            logger.info(
                "Reserved %d seats on flight %d for booking %s (reservation %d)",
                seat_count,
                flight_id,
                booking_id,
                reservation["id"],
            )

            return flight_pb2.ReserveSeatsResponse(
                reservation_id=reservation["id"],
                status=flight_pb2.ReservationStatus.Value(reservation["status"]),
            )

        except grpc.RpcError:
            raise
        except Exception as exc:
            conn.rollback()
            logger.error("ReserveSeats unexpected error: %s", exc)
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
            return flight_pb2.ReserveSeatsResponse()
        finally:
            conn.close()

    # ── ReleaseReservation ─────────────────────────────────────

    def ReleaseReservation(self, request, context):
        booking_id = request.booking_id

        conn = get_db_connection()
        try:
            conn.autocommit = False
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute(
                """
                SELECT * FROM seat_reservations
                WHERE booking_id = %s AND status = 'ACTIVE'
                FOR UPDATE
                """,
                (booking_id,),
            )
            reservation = cur.fetchone()

            if not reservation:
                conn.rollback()
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Active reservation for booking {booking_id} not found",
                )
                return flight_pb2.ReleaseReservationResponse()

            # ── Atomic: return seats + update reservation status ──
            cur.execute(
                """
                UPDATE flights
                SET available_seats = available_seats + %s, updated_at = NOW()
                WHERE id = %s
                """,
                (reservation["seat_count"], reservation["flight_id"]),
            )
            cur.execute(
                """
                UPDATE seat_reservations
                SET status = 'RELEASED', updated_at = NOW()
                WHERE id = %s
                """,
                (reservation["id"],),
            )
            conn.commit()

            flight_id = reservation["flight_id"]

            # ── Invalidate cache ──
            cache.delete(f"flight:{flight_id}")
            cache.delete_pattern("search:*")

            logger.info("Released reservation for booking %s", booking_id)
            return flight_pb2.ReleaseReservationResponse(success=True)

        except grpc.RpcError:
            raise
        except Exception as exc:
            conn.rollback()
            logger.error("ReleaseReservation unexpected error: %s", exc)
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
            return flight_pb2.ReleaseReservationResponse()
        finally:
            conn.close()


# ─────────────────────── Server bootstrap ──────────────────────


def serve():
    api_key = os.environ.get("GRPC_AUTH_KEY", "default-secret-key")
    port = os.environ.get("GRPC_PORT", "50051")

    # Run migrations with retry (wait for Postgres)
    for attempt in range(30):
        try:
            run_migrations()
            break
        except Exception as exc:
            logger.warning("Migration attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2)
    else:
        logger.error("Failed to apply migrations after 30 attempts")
        sys.exit(1)

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[AuthInterceptor(api_key)],
    )
    flight_pb2_grpc.add_FlightServiceServicer_to_server(
        FlightServiceServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("Flight Service started on port %s", port)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
