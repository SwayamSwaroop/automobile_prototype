from __future__ import annotations

import copy
import logging
import queue
import threading
from dataclasses import dataclass
from logging.handlers import QueueHandler, QueueListener
from typing import Any


@dataclass(frozen=True)
class LoggingQueueSnapshot:
    """
    Snapshot of the current logging queue health.

    This can later be exposed through application metrics
    or a health endpoint.
    """

    queue_size: int
    queue_capacity: int
    dropped_total: int
    listener_errors_total: int
    listener_alive: bool


class LoggingQueueStats:
    """
    Thread-safe statistics for the logging pipeline.

    Tracks:
    - Logs dropped because the queue was full
    - Errors raised while the background listener was
      processing logs
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        self._dropped_total = 0
        self._listener_errors_total = 0

    def increment_dropped(
        self,
    ) -> None:
        """Increment dropped-log count."""

        with self._lock:
            self._dropped_total += 1

    def increment_listener_error(
        self,
    ) -> None:
        """Increment listener processing error count."""

        with self._lock:
            self._listener_errors_total += 1

    @property
    def dropped_total(
        self,
    ) -> int:
        """Return total number of dropped log records."""

        with self._lock:
            return self._dropped_total

    @property
    def listener_errors_total(
        self,
    ) -> int:
        """Return total listener processing errors."""

        with self._lock:
            return self._listener_errors_total


class NonBlockingQueueHandler(
    QueueHandler
):
    """
    Non-blocking logging queue producer.

    Business APIs must never wait for logging.

    Flow:

        logger.info(...)
                |
                v
        NonBlockingQueueHandler
                |
                v
        queue.put_nowait(...)
                |
          +-----+-----+
          |           |
        success      full
          |           |
          v           v
        queued       drop log
                      |
                      v
                API continues
    """

    def __init__(
        self,
        log_queue: queue.Queue[Any],
        stats: LoggingQueueStats,
    ) -> None:
        super().__init__(
            log_queue
        )

        self._stats = stats

    def prepare(
        self,
        record: logging.LogRecord,
    ) -> logging.LogRecord:
        """
        Prepare a log record for the queue.

        Python's default QueueHandler.prepare() formats
        the record before putting it into the queue.

        We do not want expensive formatting on the
        business-request thread.

        Therefore, we only make a shallow copy here.

        JSON formatting and stdout writing happen later
        inside the QueueListener thread.
        """

        return copy.copy(
            record
        )

    def enqueue(
        self,
        record: logging.LogRecord,
    ) -> None:
        """
        Put the record into the queue without blocking.

        IMPORTANT:
        Never replace put_nowait() with queue.put()
        because queue.put() may block when the queue is full.
        """

        try:
            self.queue.put_nowait(
                record
            )

        except queue.Full:
            #
            # Logging is overloaded.
            #
            # Drop the operational log instead of slowing
            # or blocking the business API.
            #
            self._stats.increment_dropped()

        except Exception:
            #
            # Any unexpected queue problem must remain
            # isolated from the business API.
            #
            self._stats.increment_dropped()

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:
        """
        Emit a log record safely.

        No exception from this method is allowed to
        propagate back into logger.info(), logger.error(),
        etc.
        """

        try:
            prepared_record = self.prepare(
                record
            )

            self.enqueue(
                prepared_record
            )

        except Exception:
            #
            # Absolute fail-open protection.
            #
            # Logging failure must never fail an API.
            #
            self._stats.increment_dropped()


class SafeQueueListener(
    QueueListener
):
    """
    Background listener for queued logs.

    It runs outside the FastAPI request execution path.

    Responsibilities:
    - Read records from the queue
    - Send records to stdout handler
    - Allow formatter to create JSON/console output
    - Prevent handler failures from killing the listener
    """

    def __init__(
        self,
        log_queue: queue.Queue[Any],
        *handlers: logging.Handler,
        stats: LoggingQueueStats,
    ) -> None:
        super().__init__(
            log_queue,
            *handlers,
            respect_handler_level=True,
        )

        self._stats = stats

    def handle(
        self,
        record: logging.LogRecord,
    ) -> None:
        """
        Process one queued log record safely.

        If a formatter or output handler fails, the listener
        continues instead of crashing.
        """

        try:
            super().handle(
                record
            )

        except Exception:
            self._stats.increment_listener_error()

            #
            # IMPORTANT:
            #
            # Do not call logger.error() here.
            #
            # Doing that would send another record back into
            # the same broken logging pipeline and could create
            # recursive logging.
            #

    def enqueue_sentinel(
        self,
    ) -> None:
        """
        Insert QueueListener shutdown sentinel safely.

        QueueListener.stop() needs to insert a special
        sentinel into the queue.

        If the queue is completely full, normal Python
        QueueListener behavior may fail.

        To guarantee shutdown can proceed, discard an older
        operational log until there is room for the sentinel.
        """

        while True:
            try:
                self.queue.put_nowait(
                    self._sentinel
                )

                return

            except queue.Full:
                try:
                    #
                    # Remove one queued operational log to make
                    # room for the shutdown sentinel.
                    #
                    self.queue.get_nowait()

                    if hasattr(
                        self.queue,
                        "task_done",
                    ):
                        self.queue.task_done()

                    self._stats.increment_dropped()

                except queue.Empty:
                    #
                    # Queue state changed between Full and get.
                    # Retry.
                    #
                    continue

            except Exception:
                #
                # We still do not want shutdown to crash because
                # of logging.
                #
                self._stats.increment_listener_error()

                return

    def stop_with_timeout(
        self,
        timeout_seconds: float,
    ) -> bool:
        """
        Stop the background listener with a bounded timeout.

        Logging must not prevent a container from shutting
        down indefinitely.

        Returns:
            True:
                Listener stopped successfully.

            False:
                Listener did not stop within the timeout.
        """

        thread = getattr(
            self,
            "_thread",
            None,
        )

        if thread is None:
            return True

        try:
            self.enqueue_sentinel()

        except Exception:
            self._stats.increment_listener_error()

            return False

        thread.join(
            timeout=max(
                timeout_seconds,
                0.1,
            )
        )

        stopped = not thread.is_alive()

        if stopped:
            self._thread = None

        return stopped
