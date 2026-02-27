import pytest
import asyncio
from datetime import datetime

from models import LogEntry, AnalysisResult
from agents import ErrorDetector, Analyzer
from config import settings


class TestErrorDetector:
    """Tests for the ErrorDetector class."""

    def test_detect_error(self):
        detector = ErrorDetector()

        log = LogEntry(
            timestamp=datetime.now(),
            level="ERROR",
            node="/move_base",
            message="Failed to get robot pose",
            raw_line="[ERROR] Failed to get robot pose",
        )

        result = detector.detect(log)

        assert result.is_error is True
        assert result.severity == "high"
        assert len(result.matched_keywords) > 0

    def test_detect_warning(self):
        detector = ErrorDetector()

        log = LogEntry(
            timestamp=datetime.now(),
            level="WARN",
            node="/sensor",
            message="Laser scan delayed",
            raw_line="[WARN] Laser scan delayed",
        )

        result = detector.detect(log)

        assert result.is_warning is True
        assert result.severity == "medium"

    def test_detect_normal(self):
        detector = ErrorDetector()

        log = LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            node="/test",
            message="Normal operation",
            raw_line="[INFO] Normal operation",
        )

        result = detector.detect(log)

        assert result.is_error is False
        assert result.is_warning is False
        assert result.severity == "low"

    def test_error_type_classification(self):
        detector = ErrorDetector()

        test_cases = [
            ("Transform timeout", "Transform Timeout"),
            ("Failed to plan path", "Planning Failure"),
            ("Sensor not responding", "Sensor Timeout"),
            ("Connection refused", "Hardware Connection"),
        ]

        for message, expected_type in test_cases:
            log = LogEntry(
                timestamp=datetime.now(),
                level="ERROR",
                node="/test",
                message=message,
                raw_line=f"[ERROR] {message}",
            )

            result = detector.detect(log)
            assert result.error_type == expected_type, f"Expected {expected_type} for '{message}'"


class TestAnalyzer:
    """Tests for the Analyzer class."""

    @pytest.mark.asyncio
    async def test_mock_analysis(self):
        """Test analyzer without API key (mock mode)."""
        analyzer = Analyzer(api_key="")

        logs = [
            LogEntry(
                timestamp=datetime.now(),
                level="INFO",
                node="/move_base",
                message="Starting navigation",
                raw_line="[INFO] Starting navigation",
            ),
            LogEntry(
                timestamp=datetime.now(),
                level="ERROR",
                node="/move_base",
                message="Transform timeout",
                raw_line="[ERROR] Transform timeout",
            ),
        ]

        result = await analyzer.analyze(logs)

        assert result is not None
        assert isinstance(result, AnalysisResult)
        assert result.error_type is not None
        assert result.root_cause is not None
        assert len(result.corrective_actions) > 0
        assert result.metadata.get("mock") is True

    @pytest.mark.asyncio
    async def test_empty_logs(self):
        """Test analyzer with empty logs."""
        analyzer = Analyzer(api_key="")

        result = await analyzer.analyze([])

        assert result is None

    def test_stats(self):
        analyzer = Analyzer(api_key="")

        stats = analyzer.get_stats()

        assert "total_analyses" in stats
        assert "successful_analyses" in stats
        assert "failed_analyses" in stats


class TestLogEntry:
    """Tests for the LogEntry model."""

    def test_is_error(self):
        error_log = LogEntry(
            timestamp=datetime.now(),
            level="ERROR",
            node="/test",
            message="Error message",
            raw_line="[ERROR] Error message",
        )

        assert error_log.is_error() is True

        fatal_log = LogEntry(
            timestamp=datetime.now(),
            level="FATAL",
            node="/test",
            message="Fatal message",
            raw_line="[FATAL] Fatal message",
        )

        assert fatal_log.is_error() is True

        info_log = LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            node="/test",
            message="Info message",
            raw_line="[INFO] Info message",
        )

        assert info_log.is_error() is False

    def test_is_warning(self):
        warn_log = LogEntry(
            timestamp=datetime.now(),
            level="WARN",
            node="/test",
            message="Warning message",
            raw_line="[WARN] Warning message",
        )

        assert warn_log.is_warning() is True

        error_log = LogEntry(
            timestamp=datetime.now(),
            level="ERROR",
            node="/test",
            message="Error message",
            raw_line="[ERROR] Error message",
        )

        assert error_log.is_warning() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
