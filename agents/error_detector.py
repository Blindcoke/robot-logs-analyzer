import re
from typing import Callable, List, Optional, Tuple
from dataclasses import dataclass

from models import LogEntry


@dataclass
class DetectionResult:
    """Result of error detection."""
    is_error: bool
    is_warning: bool
    severity: str  # critical, high, medium, low
    matched_keywords: List[str]
    error_type: Optional[str] = None


class ErrorDetector:
    """Detects errors and warnings in log entries."""

    # Severity classification rules
    SEVERITY_RULES = {
        "critical": [
            r"FATAL",
            r"CRITICAL",
            r"emergency stop",
            r"emergency_stop",
            r"power failure",
            r"hardware failure",
            r"collision",
            r"safety.*violated",
        ],
        "high": [
            r"ERROR",
            r"Exception",
            r"exception",
            r"failed",
            r"Failed",
            r"unable",
            r"Unable",
            r"cannot",
            r"Cannot",
            r"timeout",
            r"Timeout",
            r"refused",
            r"Refused",
        ],
        "medium": [
            r"WARN",
            r"Warning",
            r"warning",
            r"deprecated",
            r"retry",
            r"Retry",
            r"unstable",
        ],
        "low": [
            r"DEBUG",
            r"trace",
            r"notice",
        ],
    }

    # Error type classification patterns
    ERROR_TYPES = {
        "Transform Timeout": [
            r"transform.*timeout",
            r"lookup.*transform",
            r"can.*t.*lookup",
            r"no.*transform",
        ],
        "Planning Failure": [
            r"plan.*fail",
            r"plan.*path",
            r"no.*valid.*path",
            r"goal.*unreachable",
            r"planning.*error",
        ],
        "Sensor Timeout": [
            r"sensor.*timeout",
            r"laser.*timeout",
            r"camera.*timeout",
            r"no.*data.*received",
            r"sensor.*not.*respond",
            r"laser.*not.*respond",
        ],
        "Hardware Connection": [
            r"connection.*refused",
            r"unable.*connect",
            r"hardware.*disconnected",
            r"communication.*error",
        ],
        "Joint Limit": [
            r"joint.*limit",
            r"limit.*exceeded",
            r"out.*of.*range",
            r"position.*limit",
        ],
        "Collision Detected": [
            r"collision",
            r"in.*collision",
            r"obstacle.*detected",
            r"contact.*detected",
        ],
        "Navigation Failure": [
            r"navigation.*fail",
            r"move_base.*fail",
            r"abort.*navigation",
        ],
        "Controller Error": [
            r"controller.*error",
            r"control.*fail",
            r"tracking.*error",
        ],
        "SLAM Error": [
            r"slam.*error",
            r"localization.*fail",
            r"amcl.*error",
        ],
    }

    def __init__(
        self,
        error_keywords: Optional[List[str]] = None,
        warning_keywords: Optional[List[str]] = None,
        on_error_detected: Optional[Callable[[
            LogEntry, DetectionResult], None]] = None,
    ):
        self.error_keywords = error_keywords or []
        self.warning_keywords = warning_keywords or []
        self.on_error_detected = on_error_detected

        # Compile severity patterns
        self._severity_patterns = {
            severity: [re.compile(pattern, re.IGNORECASE)
                       for pattern in patterns]
            for severity, patterns in self.SEVERITY_RULES.items()
        }

        # Compile error type patterns
        self._error_type_patterns = {
            error_type: [re.compile(pattern, re.IGNORECASE)
                         for pattern in patterns]
            for error_type, patterns in self.ERROR_TYPES.items()
        }

        # Compile custom keyword patterns
        self._custom_error_patterns = [
            re.compile(re.escape(kw), re.IGNORECASE) for kw in self.error_keywords
        ]
        self._custom_warning_patterns = [
            re.compile(re.escape(kw), re.IGNORECASE) for kw in self.warning_keywords
        ]

        # Statistics
        self._stats = {
            "total_checked": 0,
            "errors_detected": 0,
            "warnings_detected": 0,
        }

    def detect(self, log_entry: LogEntry) -> DetectionResult:
        """Analyze a log entry and detect errors/warnings."""
        self._stats["total_checked"] += 1

        text = f"{log_entry.level} {log_entry.node} {log_entry.message}"
        matched_keywords = []

        # Check severity based on log level
        severity = self._classify_severity(log_entry, text)

        # Check for error patterns
        is_error = (
            log_entry.is_error() or
            severity in ("critical", "high") or
            self._check_patterns(
                text, self._custom_error_patterns, matched_keywords)
        )

        # Check for warning patterns
        is_warning = (
            log_entry.is_warning() or
            severity == "medium" or
            self._check_patterns(
                text, self._custom_warning_patterns, matched_keywords)
        )

        # Classify error type
        error_type = None
        if is_error:
            error_type = self._classify_error_type(text)
            self._stats["errors_detected"] += 1
        elif is_warning:
            self._stats["warnings_detected"] += 1

        # Collect matched keywords
        if log_entry.level.upper() in ("ERROR", "FATAL", "CRITICAL"):
            matched_keywords.append(log_entry.level)

        result = DetectionResult(
            is_error=is_error,
            is_warning=is_warning,
            severity=severity,
            matched_keywords=list(set(matched_keywords)),
            error_type=error_type,
        )

        # Trigger callback if error detected
        if is_error and self.on_error_detected:
            self.on_error_detected(log_entry, result)

        return result

    def _classify_severity(self, log_entry: LogEntry, text: str) -> str:
        """Classify the severity of a log entry."""
        # Check patterns in order of severity
        for severity in ["critical", "high", "medium", "low"]:
            patterns = self._severity_patterns.get(severity, [])
            for pattern in patterns:
                if pattern.search(text):
                    return severity

        # Default based on log level
        level = log_entry.level.upper()
        if level in ("FATAL", "CRITICAL"):
            return "critical"
        elif level == "ERROR":
            return "high"
        elif level == "WARN":
            return "medium"
        else:
            return "low"

    def _classify_error_type(self, text: str) -> Optional[str]:
        """Classify the type of error."""
        for error_type, patterns in self._error_type_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    return error_type
        return "Unknown Error"

    def _check_patterns(
        self,
        text: str,
        patterns: List[re.Pattern],
        matched_keywords: List[str]
    ) -> bool:
        """Check if any pattern matches the text."""
        matched = False
        for pattern in patterns:
            if pattern.search(text):
                matched_keywords.append(pattern.pattern)
                matched = True
        return matched

    def should_analyze(self, log_entry: LogEntry) -> bool:
        """Quick check if log entry should be analyzed."""
        result = self.detect(log_entry)
        return result.is_error or result.is_warning

    def get_stats(self) -> dict:
        """Get detection statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset detection statistics."""
        self._stats = {
            "total_checked": 0,
            "errors_detected": 0,
            "warnings_detected": 0,
        }


# For testing the detector directly
if __name__ == "__main__":
    from datetime import datetime

    detector = ErrorDetector()

    test_entries = [
        LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            node="/test",
            message="Normal operation",
            raw_line="[INFO] Normal operation",
        ),
        LogEntry(
            timestamp=datetime.now(),
            level="ERROR",
            node="/move_base",
            message="Failed to get robot pose: Transform timeout",
            raw_line="[ERROR] Failed to get robot pose: Transform timeout",
        ),
        LogEntry(
            timestamp=datetime.now(),
            level="WARN",
            node="/sensor",
            message="Laser scan message delayed",
            raw_line="[WARN] Laser scan message delayed",
        ),
        LogEntry(
            timestamp=datetime.now(),
            level="FATAL",
            node="/hardware",
            message="Emergency stop triggered",
            raw_line="[FATAL] Emergency stop triggered",
        ),
    ]

    for entry in test_entries:
        result = detector.detect(entry)
        print(f"[{entry.level}] {entry.message}")
        print(f"  Error: {result.is_error}, Warning: {result.is_warning}")
        print(f"  Severity: {result.severity}, Type: {result.error_type}")
        print()

    print("Stats:", detector.get_stats())
