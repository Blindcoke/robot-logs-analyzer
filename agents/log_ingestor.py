import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from models import LogEntry


class LogFileHandler(FileSystemEventHandler):
    """Handles file system events for log file monitoring."""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self._last_position = 0
        self._file_path: Optional[Path] = None

    def set_file_path(self, file_path: Path):
        """Set the file path and initialize position."""
        self._file_path = file_path
        if file_path.exists():
            self._last_position = file_path.stat().st_size

    def on_modified(self, event):
        """Called when the log file is modified."""
        if hasattr(event, 'src_path'):
            # Handle both absolute and relative paths
            event_path = Path(event.src_path).resolve()
            watch_path = self._file_path.resolve() if self._file_path else None
            if watch_path and event_path == watch_path:
                self._read_new_lines()

    def on_created(self, event):
        """Called when the log file is created."""
        if hasattr(event, 'src_path'):
            event_path = Path(event.src_path).resolve()
            watch_path = self._file_path.resolve() if self._file_path else None
            if watch_path and event_path == watch_path:
                self._last_position = 0
                self._read_new_lines()

    def _read_new_lines(self):
        """Read new lines added to the file."""
        if not self._file_path or not self._file_path.exists():
            return

        with open(self._file_path, "r") as f:
            f.seek(self._last_position)
            new_lines = f.readlines()
            self._last_position = f.tell()

        for line in new_lines:
            line = line.strip()
            if line:
                self.callback(line)

    def read_all(self):
        """Read all lines from the file (for initial load)."""
        if not self._file_path or not self._file_path.exists():
            return

        with open(self._file_path, "r") as f:
            lines = f.readlines()
            self._last_position = f.tell()

        for line in lines:
            line = line.strip()
            if line:
                self.callback(line)


class LogIngestor:
    """Ingests and parses ROS log files."""

    # ROS log format regex patterns
    ROS_LOG_PATTERN = re.compile(
        r"\[(\w+)\]\s+\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\](?:\s+\[([^\]]+)\])?\s*:\s*(.+)"
    )

    # Alternative simpler pattern for some ROS formats
    ROS_SIMPLE_PATTERN = re.compile(
        r"\[(\w+)\]\s*\[([^\]]+)\]\s*:\s*(.+)"
    )

    def __init__(
        self,
        log_file_path: str,
        on_log_entry: Optional[Callable[[LogEntry], None]] = None,
    ):
        self.log_file_path = Path(log_file_path)
        self.on_log_entry = on_log_entry
        self._observer: Optional[Observer] = None
        self._handler: Optional[LogFileHandler] = None
        self._running = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def _parse_ros_log(self, line: str) -> Optional[LogEntry]:
        """Parse a ROS log line into a LogEntry."""
        # Try full pattern first
        match = self.ROS_LOG_PATTERN.match(line)

        if match:
            level = match.group(1)
            timestamp_str = match.group(2)
            node = match.group(3) or "unknown"
            message = match.group(4)

            try:
                timestamp = datetime.strptime(
                    timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                try:
                    timestamp = datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    timestamp = datetime.now()

            return LogEntry(
                timestamp=timestamp,
                level=level.upper(),
                node=node,
                message=message.strip(),
                raw_line=line,
            )

        # Try simpler pattern
        match = self.ROS_SIMPLE_PATTERN.match(line)
        if match:
            level = match.group(1)
            node_or_time = match.group(2)
            message = match.group(3)

            # Determine if second group is node or timestamp
            if "/" in node_or_time:
                node = node_or_time
                timestamp = datetime.now()
            else:
                node = "unknown"
                try:
                    timestamp = datetime.strptime(
                        node_or_time, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    timestamp = datetime.now()

            return LogEntry(
                timestamp=timestamp,
                level=level.upper(),
                node=node,
                message=message.strip(),
                raw_line=line,
            )

        # Fallback: treat entire line as message
        return LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            node="unknown",
            message=line,
            raw_line=line,
        )

    def _on_new_line(self, line: str):
        """Callback for new log lines."""
        log_entry = self._parse_ros_log(line)
        if log_entry and self.on_log_entry:
            self.on_log_entry(log_entry)

    async def start(self) -> None:
        """Start monitoring the log file."""
        self._running = True

        # Ensure the log file exists
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file_path.exists():
            self.log_file_path.touch()

        # Set up file watcher
        self._handler = LogFileHandler(self._on_new_line)
        self._handler.set_file_path(self.log_file_path)

        self._observer = Observer()
        self._observer.schedule(
            self._handler,
            str(self.log_file_path.parent),
            recursive=False
        )
        self._observer.start()

        # Read existing content
        self._handler.read_all()

        print(f"Log ingestor started. Monitoring: {self.log_file_path}")

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    def stop(self) -> None:
        """Stop monitoring the log file."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        print("Log ingestor stopped.")

    async def ingest_line(self, line: str) -> LogEntry:
        """Manually ingest a single log line."""
        log_entry = self._parse_ros_log(line)
        if self.on_log_entry:
            self.on_log_entry(log_entry)
        return log_entry


# For testing the ingestor directly
if __name__ == "__main__":
    def on_entry(entry: LogEntry):
        print(f"[{entry.level}] [{entry.node}] {entry.message}")

    ingestor = LogIngestor("./logs/test.log", on_entry)

    try:
        asyncio.run(ingestor.start())
    except KeyboardInterrupt:
        ingestor.stop()
