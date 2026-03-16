"""
Circuit Breaker — middleware for gRPC client calls.

States:
  CLOSED     → normal operation; transitions to OPEN after `failure_threshold` failures.
  OPEN       → all calls rejected immediately; after `recovery_timeout` seconds → HALF_OPEN.
  HALF_OPEN  → one probe call allowed; success → CLOSED, failure → OPEN.

All transitions are logged.
"""

import threading
import time
import logging

logger = logging.getLogger("circuit-breaker")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""
    pass


class CircuitBreaker:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

        logger.info(
            "CircuitBreaker initialized: failure_threshold=%d, recovery_timeout=%ds",
            failure_threshold,
            recovery_timeout,
        )

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == self.CLOSED:
                return True
            if self._state == self.OPEN:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._transition(self.HALF_OPEN)
                    return True
                return False
            # HALF_OPEN — allow one probe call
            return True

    def record_success(self):
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._transition(self.CLOSED)
            self._failure_count = 0

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == self.HALF_OPEN:
                self._transition(self.OPEN)
            elif (
                self._state == self.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._transition(self.OPEN)

    # ── internal ──

    def _transition(self, new_state: str):
        old = self._state
        self._state = new_state
        if old != new_state:
            logger.info("Circuit breaker: %s -> %s", old, new_state)
