"""
Booking Service — REST API for flight bookings.

Features:
- REST endpoints for searching flights, managing bookings
- gRPC client to Flight Service with:
  - API Key authentication (metadata)
  - Retry with exponential backoff (3 attempts, UNAVAILABLE/DEADLINE_EXCEEDED only)
  - Circuit Breaker middleware (configurable via env)
- PostgreSQL for booking storage
"""

import os
import sys
import time
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal

import grpc
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn

import flight_pb2
import flight_pb2_grpc
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("booking-service")

app = FastAPI(title="Booking Service")


# ─────────────────────────── Database ───────────────────────────


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "booking_db"),
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


# ──────────────── gRPC Client with Retry + Circuit Breaker ─────


RETRYABLE_CODES = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}
MAX_RETRIES = 3


class FlightServiceClient:
    """
    gRPC client wrapper with:
    - API Key authentication in metadata
    - Retry with exponential backoff for UNAVAILABLE / DEADLINE_EXCEEDED
    - Circuit Breaker (as external middleware, not inside business logic)
    """

    def __init__(self, host: str, api_key: str, cb: CircuitBreaker):
        self.channel = grpc.insecure_channel(host)
        self.stub = flight_pb2_grpc.FlightServiceStub(self.channel)
        self.api_key = api_key
        self.cb = cb

    def _metadata(self):
        return [("x-api-key", self.api_key)]

    def _call(self, method, request, *, idempotent: bool = True):
        """Execute a gRPC call with circuit breaker check and retry logic."""

        # ── Circuit Breaker gate ──
        if not self.cb.can_execute():
            raise HTTPException(
                status_code=503,
                detail="Flight service temporarily unavailable (circuit breaker OPEN)",
            )

        max_attempts = MAX_RETRIES if idempotent else 1
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = method(request, metadata=self._metadata(), timeout=5)
                self.cb.record_success()
                return response

            except grpc.RpcError as exc:
                last_error = exc
                code = exc.code()

                # Only retry on transient errors
                if code in RETRYABLE_CODES:
                    self.cb.record_failure()
                    if attempt < max_attempts:
                        backoff = 0.1 * (2 ** attempt)  # 100ms, 200ms, 400ms
                        logger.warning(
                            "Retry %d/%d after %.0fms (code=%s)",
                            attempt + 1,
                            max_attempts,
                            backoff * 1000,
                            code.name,
                        )
                        time.sleep(backoff)
                        # Re-check circuit breaker
                        if not self.cb.can_execute():
                            raise HTTPException(
                                status_code=503,
                                detail="Flight service temporarily unavailable (circuit breaker OPEN)",
                            )
                        continue

                # Non-retryable — break immediately
                break

        # ── Translate gRPC error to HTTP error ──
        if last_error:
            code = last_error.code()
            detail = last_error.details()
            if code == grpc.StatusCode.NOT_FOUND:
                raise HTTPException(status_code=404, detail=detail)
            if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
                raise HTTPException(status_code=409, detail=detail)
            if code == grpc.StatusCode.INVALID_ARGUMENT:
                raise HTTPException(status_code=400, detail=detail)
            if code == grpc.StatusCode.UNAUTHENTICATED:
                raise HTTPException(status_code=500, detail="Internal auth error")
            if code in RETRYABLE_CODES:
                raise HTTPException(
                    status_code=503,
                    detail=f"Flight service unavailable: {detail}",
                )
            raise HTTPException(status_code=500, detail=f"Flight service error: {detail}")

        raise HTTPException(status_code=500, detail="Unknown error")

    # ── Public methods ──

    def get_flight(self, flight_id: int):
        return self._call(
            self.stub.GetFlight,
            flight_pb2.GetFlightRequest(id=flight_id),
        )

    def search_flights(self, origin: str, destination: str, date: str | None = None):
        req = flight_pb2.SearchFlightsRequest(origin=origin, destination=destination)
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            req.date.FromDatetime(dt)
        return self._call(self.stub.SearchFlights, req)

    def reserve_seats(self, flight_id: int, seat_count: int, booking_id: str):
        return self._call(
            self.stub.ReserveSeats,
            flight_pb2.ReserveSeatsRequest(
                flight_id=flight_id, seat_count=seat_count, booking_id=booking_id
            ),
            idempotent=True,  # booking_id guarantees idempotency
        )

    def release_reservation(self, booking_id: str):
        return self._call(
            self.stub.ReleaseReservation,
            flight_pb2.ReleaseReservationRequest(booking_id=booking_id),
            idempotent=True,
        )


# ── Initialize circuit breaker + client (at module level) ──

cb = CircuitBreaker(
    failure_threshold=int(os.environ.get("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=int(os.environ.get("CB_RECOVERY_TIMEOUT", "30")),
)

flight_client: FlightServiceClient | None = None


@app.on_event("startup")
def startup():
    global flight_client
    flight_client = FlightServiceClient(
        host=os.environ.get("FLIGHT_SERVICE_HOST", "flight-service:50051"),
        api_key=os.environ.get("GRPC_AUTH_KEY", "default-secret-key"),
        cb=cb,
    )


# ──────────────────────── Helpers ──────────────────────────────


def _flight_pb_to_dict(f) -> dict:
    return {
        "id": f.id,
        "flight_number": f.flight_number,
        "airline": f.airline,
        "origin": f.origin,
        "destination": f.destination,
        "departure_time": f.departure_time.ToDatetime().isoformat(),
        "arrival_time": f.arrival_time.ToDatetime().isoformat(),
        "total_seats": f.total_seats,
        "available_seats": f.available_seats,
        "price": f.price,
        "status": flight_pb2.FlightStatus.Name(f.status),
    }


def _booking_row_to_dict(b) -> dict:
    return {
        "id": str(b["id"]),
        "user_id": b["user_id"],
        "flight_id": b["flight_id"],
        "passenger_name": b["passenger_name"],
        "passenger_email": b["passenger_email"],
        "seat_count": b["seat_count"],
        "total_price": float(b["total_price"]),
        "status": b["status"],
        "created_at": b["created_at"].isoformat(),
        "updated_at": b["updated_at"].isoformat(),
    }


# ──────────────────────── REST Endpoints ───────────────────────


class CreateBookingRequest(BaseModel):
    user_id: str
    flight_id: int
    passenger_name: str
    passenger_email: str
    seat_count: int


@app.get("/flights")
def search_flights(
    origin: str = Query(..., description="IATA code"),
    destination: str = Query(..., description="IATA code"),
    date: str | None = Query(None, description="YYYY-MM-DD"),
):
    """Proxy to Flight Service SearchFlights."""
    resp = flight_client.search_flights(origin, destination, date)
    return [_flight_pb_to_dict(f) for f in resp.flights]


@app.get("/flights/{flight_id}")
def get_flight(flight_id: int):
    """Proxy to Flight Service GetFlight."""
    resp = flight_client.get_flight(flight_id)
    return _flight_pb_to_dict(resp.flight)


@app.post("/bookings", status_code=201)
def create_booking(req: CreateBookingRequest):
    """
    Create a booking:
    1. GetFlight — fetch flight info & price
    2. ReserveSeats — atomically reserve seats
    3. Insert booking record into DB
    On failure at any step — no partial state is left.
    """
    booking_id = str(uuid.uuid4())

    # Step 1: get flight info
    flight_resp = flight_client.get_flight(req.flight_id)
    flight = flight_resp.flight

    # Step 2: reserve seats (idempotent via booking_id)
    flight_client.reserve_seats(req.flight_id, req.seat_count, booking_id)

    # Step 3: calculate price snapshot
    total_price = req.seat_count * flight.price

    # Step 4: persist booking
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            INSERT INTO bookings
                (id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'CONFIRMED')
            RETURNING *
            """,
            (
                booking_id,
                req.user_id,
                req.flight_id,
                req.passenger_name,
                req.passenger_email,
                req.seat_count,
                total_price,
            ),
        )
        booking = cur.fetchone()
        conn.commit()
        cur.close()
    except Exception as exc:
        conn.rollback()
        # Compensate: release reservation if DB write failed
        try:
            flight_client.release_reservation(booking_id)
        except Exception:
            logger.error("Failed to release reservation after DB error for booking %s", booking_id)
        raise HTTPException(status_code=500, detail=f"Failed to create booking: {exc}")
    finally:
        conn.close()

    return _booking_row_to_dict(booking)


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()
    cur.close()
    conn.close()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return _booking_row_to_dict(booking)


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()

    if not booking:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking["status"] != "CONFIRMED":
        cur.close()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel booking in status {booking['status']}",
        )

    # Release reservation in Flight Service
    try:
        flight_client.release_reservation(str(booking["id"]))
    except HTTPException as exc:
        if exc.status_code != 404:
            cur.close()
            conn.close()
            raise

    # Update booking status
    cur.execute(
        """
        UPDATE bookings SET status = 'CANCELLED', updated_at = NOW()
        WHERE id = %s
        RETURNING *
        """,
        (booking_id,),
    )
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return _booking_row_to_dict(updated)


@app.get("/bookings")
def list_bookings(user_id: str = Query(...)):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM bookings WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )
    bookings = cur.fetchall()
    cur.close()
    conn.close()
    return [_booking_row_to_dict(b) for b in bookings]


# ──────────────────────── Main ─────────────────────────────────


if __name__ == "__main__":
    # Apply migrations with retry
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

    uvicorn.run(app, host="0.0.0.0", port=8080)
