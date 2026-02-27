import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from models import LogEntry


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class ContextEngine:
    """Manages sliding window context for log analysis."""

    def __init__(
        self,
        window_size: int = 50,
        timeout_sec: int = 30,
        on_flush: Optional[Callable[[List[LogEntry]], None]] = None,
    ):
        self.window_size = window_size
        self.timeout_sec = timeout_sec
        self.on_flush = on_flush

        self._buffer: deque[LogEntry] = deque(maxlen=window_size)
        self._last_flush_time: datetime = utc_now()
        self._lock = asyncio.Lock()
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None

    async def add(self, log_entry: LogEntry) -> None:
        """Add a log entry to the context window."""
        async with self._lock:
            self._buffer.append(log_entry)

    async def get_context(self) -> List[LogEntry]:
        """Get current context window contents."""
        async with self._lock:
            return list(self._buffer)

    async def clear(self) -> None:
        """Clear the context window."""
        async with self._lock:
            self._buffer.clear()

    async def flush(self) -> List[LogEntry]:
        """Flush the current context window and return contents."""
        async with self._lock:
            context = list(self._buffer)
            self._buffer.clear()
            self._last_flush_time = utc_now()
            return context

    async def should_flush(self, triggered_by_error: bool = False) -> bool:
        """Check if the buffer should be flushed."""
        async with self._lock:
            if not self._buffer:
                return False

            # Flush if triggered by error
            if triggered_by_error:
                return True

            # Flush if buffer is full
            if len(self._buffer) >= self.window_size:
                return True

            # Flush if timeout reached
            time_since_flush = datetime.utcnow() - self._last_flush_time
            if time_since_flush >= timedelta(seconds=self.timeout_sec):
                return True

            return False

    async def _flush_loop(self) -> None:
        """Background task to periodically flush on timeout."""
        while self._running:
            await asyncio.sleep(5)  # Check every 5 seconds

            if await self.should_flush(triggered_by_error=False):
                context = await self.flush()
                if context and self.on_flush:
                    try:
                        self.on_flush(context)
                    except Exception as e:
                        print(f"Error in flush callback: {e}")

    async def start(self) -> None:
        """Start the context engine."""
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        print(
            f"Context engine started (window_size={self.window_size}, timeout={self.timeout_sec}s)")

    def stop(self) -> None:
        """Stop the context engine."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        print("Context engine stopped.")

    def get_stats(self) -> dict:
        """Get current statistics."""
        return {
            "buffer_size": len(self._buffer),
            "window_size": self.window_size,
            "last_flush": self._last_flush_time.isoformat(),
        }


class SmartContextEngine(ContextEngine):
    """Extended context engine with intelligent grouping."""

    def __init__(
        self,
        window_size: int = 50,
        timeout_sec: int = 30,
        error_window_size: int = 20,
        on_flush: Optional[Callable[[List[LogEntry]], None]] = None,
        on_error_context: Optional[Callable[[List[LogEntry]], None]] = None,
    ):
        super().__init__(window_size, timeout_sec, on_flush)
        self.error_window_size = error_window_size
        self.on_error_context = on_error_context
        self._error_buffer: deque[LogEntry] = deque(maxlen=error_window_size)

    async def add(self, log_entry: LogEntry) -> bool:
        """Add a log entry and return True if this is an error entry."""
        await super().add(log_entry)

        is_error = log_entry.is_error()

        if is_error:
            async with self._lock:
                # Build error context from recent history
                error_context = list(self._buffer)[-self.error_window_size:]
                self._error_buffer = deque(
                    error_context, maxlen=self.error_window_size)

                if self.on_error_context:
                    try:
                        await self.on_error_context(list(self._error_buffer))
                    except Exception as e:
                        print(f"Error in error context callback: {e}")

        return is_error

    async def get_error_context(self) -> List[LogEntry]:
        """Get the error-specific context window."""
        async with self._lock:
            return list(self._error_buffer)

    async def flush_error_context(self) -> List[LogEntry]:
        """Flush and return the error context."""
        async with self._lock:
            context = list(self._error_buffer)
            self._error_buffer.clear()
            return context

    async def clear(self) -> None:
        """Clear both context and error buffers."""
        await super().clear()
        async with self._lock:
            self._error_buffer.clear()


# For testing the context engine directly
if __name__ == "__main__":
    async def main():
        def on_flush(context: List[LogEntry]):
            print(f"Flushed {len(context)} entries")

        engine = SmartContextEngine(
            window_size=10,
            timeout_sec=5,
            on_flush=on_flush,
            on_error_context=lambda ctx: print(
                f"Error context: {len(ctx)} entries"),
        )

        await engine.start()

        # Simulate adding log entries
        for i in range(15):
            entry = LogEntry(
                timestamp=datetime.now(),
                level="INFO" if i < 12 else "ERROR",
                node="test_node",
                message=f"Test message {i}",
                raw_line=f"[INFO] Test message {i}",
            )
            await engine.add(entry)
            await asyncio.sleep(0.5)

        await asyncio.sleep(6)  # Wait for timeout flush
        engine.stop()

    asyncio.run(main())
