from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from .log_entry import LogEntry


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class AnalysisResult(BaseModel):
    """Structured output from AI analysis of robot logs."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "analysis_001",
                "timestamp": "2024-01-15T10:30:50.000000",
                "severity": "high",
                "error_type": "Transform Timeout",
                "root_cause": "TF tree not properly initialized between /map and /base_link frames",
                "affected_systems": ["move_base", "amcl", "robot_localization"],
                "corrective_actions": [
                    "Restart AMCL node",
                    "Check static transform publisher",
                    "Verify frame IDs in configuration"
                ],
                "confidence": 0.92,
                "context_logs": []
            }
        }
    )

    id: str = Field(..., description="Unique analysis identifier")
    timestamp: datetime = Field(
        default_factory=utc_now, description="Analysis timestamp")
    severity: str = Field(...,
                          description="Severity: critical, high, medium, low")
    error_type: str = Field(..., description="Classification of the error")
    root_cause: str = Field(..., description="Explanation of the root cause")
    affected_systems: List[str] = Field(
        default_factory=list, description="List of affected subsystems")
    corrective_actions: List[str] = Field(
        default_factory=list, description="Suggested corrective actions")
    confidence: float = Field(..., ge=0.0, le=1.0,
                              description="Confidence score 0.0-1.0")
    context_logs: List[LogEntry] = Field(
        default_factory=list, description="Log entries that triggered analysis")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump()

    def summary(self) -> str:
        """Get a human-readable summary."""
        return (
            f"[{self.severity.upper()}] {self.error_type}\n"
            f"Root Cause: {self.root_cause}\n"
            f"Confidence: {self.confidence:.0%}\n"
            f"Actions: {', '.join(self.corrective_actions[:2])}"
        )
