"""Tests for the LLM circuit breaker."""
import time
from unittest.mock import patch

from src.utils.llm.circuit_breaker import CircuitBreaker, CircuitState


def test_initial_state_is_closed():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True


def test_stays_closed_under_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True


def test_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb._failure_count == 0
    assert cb.state == CircuitState.CLOSED
    # After reset, need 3 more failures to open
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_transitions_to_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False

    # Wait for timeout
    time.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.can_execute() is True


def test_half_open_success_closes():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True


def test_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    time.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False
