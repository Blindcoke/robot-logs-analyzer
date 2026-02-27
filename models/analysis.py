from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from .log_entry import LogEntry


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class TaxonomyClassification(BaseModel):
    """SKILL.md taxonomy: category, event, error_code, component, dependency."""

    category: str = Field(
        ...,
        description="One of: INFRASTRUCTURE, QUEUE, AUTH, PERFORMANCE, EXTERNAL, APPLICATION",
    )
    event: Optional[str] = Field(None, description="Event type e.g. DB_TIMEOUT, QUEUE_OVERFLOW")
    error_code: Optional[str] = Field(None, description="Error code e.g. CONNECTION_TIMEOUT")
    component: Optional[str] = Field(None, description="System component e.g. database, message-queue")
    dependency: Optional[str] = Field(None, description="Failing dependency e.g. payment-db, rabbitmq")


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
                "context_logs": [],
                "taxonomy": None,
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
    taxonomy: Optional[TaxonomyClassification] = Field(
        None, description="SKILL.md classification (category, event, component, etc.)"
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = self.model_dump()
        # Serialize taxonomy if present
        if self.taxonomy:
            d["taxonomy"] = self.taxonomy.model_dump()
        return d

    def summary(self) -> str:
        """Get a human-readable summary."""
        return (
            f"[{self.severity.upper()}] {self.error_type}\n"
            f"Root Cause: {self.root_cause}\n"
            f"Confidence: {self.confidence:.0%}\n"
            f"Actions: {', '.join(self.corrective_actions[:2])}"
        )

    def taxonomy_line(self) -> Optional[str]:
        """Format taxonomy per SKILL.md: [SEVERITY] CATEGORY | event=... | ..."""
        if not self.taxonomy:
            return None
        t = self.taxonomy
        severity_upper = self.severity.upper()
        parts = [f"event={t.event or 'N/A'}", f"error_code={t.error_code or 'N/A'}"]
        if t.component:
            parts.append(f"component={t.component}")
        if t.dependency:
            parts.append(f"dependency={t.dependency}")
        return f"[{severity_upper}] {t.category} | " + " | ".join(parts)
