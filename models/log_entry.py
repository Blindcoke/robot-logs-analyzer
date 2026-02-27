from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class LogEntry(BaseModel):
    """Represents a single parsed log entry from ROS logs."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timestamp": "2024-01-15T10:30:45.123456",
                "level": "ERROR",
                "node": "/move_base",
                "message": "Failed to get robot pose: Transform timeout",
                "raw_line": "[ERROR] [2024-01-15 10:30:45.123456]: Failed to get robot pose: Transform timeout",
            }
        }
    )

    timestamp: datetime = Field(..., description="Log entry timestamp")
    level: str = Field(...,
                       description="Log level: DEBUG, INFO, WARN, ERROR, FATAL")
    node: str = Field(..., description="ROS node name that generated the log")
    message: str = Field(..., description="Log message content")
    raw_line: str = Field(..., description="Original raw log line")
    file_path: Optional[str] = Field(
        None, description="Source file path if available")
    line_number: Optional[int] = Field(
        None, description="Line number in source file")

    def is_error(self) -> bool:
        """Check if this log entry represents an error."""
        return self.level.upper() in ("ERROR", "FATAL", "CRITICAL")

    def is_warning(self) -> bool:
        """Check if this log entry represents a warning."""
        return self.level.upper() == "WARN"

    def __str__(self) -> str:
        return f"[{self.level}] [{self.node}] {self.message}"
