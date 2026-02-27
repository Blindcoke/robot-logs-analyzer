import json
import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from openai import AsyncOpenAI

from models import LogEntry, AnalysisResult
from config import settings


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class Analyzer:
    """Analyzes robot logs using OpenAI GPT."""

    SYSTEM_PROMPT = """You are an expert robot systems engineer specializing in ROS (Robot Operating System) and autonomous systems. Your task is to analyze robot log entries, identify the root cause of errors, and suggest corrective actions.

When analyzing logs, consider:
1. ROS-specific error patterns (TF transforms, navigation, SLAM, controllers)
2. Hardware communication issues
3. Sensor failures and timeouts
4. Planning and control errors
5. System resource constraints

Provide your analysis in a structured JSON format with the following fields:
- severity: "critical", "high", "medium", or "low"
- error_type: A concise classification of the error
- root_cause: A clear explanation of what caused the error
- affected_systems: List of ROS nodes or subsystems affected
- corrective_actions: List of specific steps to resolve the issue
- confidence: A number between 0.0 and 1.0 indicating your confidence

Be specific and actionable in your recommendations."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self.max_tokens = max_tokens
        self.temperature = temperature

        self._client: Optional[AsyncOpenAI] = None
        self._semaphore = asyncio.Semaphore(5)  # Limit concurrent API calls
        self._stats = {
            "total_analyses": 0,
            "successful_analyses": 0,
            "failed_analyses": 0,
        }

    def _get_client(self) -> AsyncOpenAI:
        """Get or create the OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("OpenAI API key not configured")
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                http_client=None,  # Use default httpx client
            )
        return self._client

    def _format_logs_for_analysis(self, logs: List[LogEntry]) -> str:
        """Format log entries for the AI prompt."""
        formatted = []
        for log in logs:
            ts = log.timestamp.strftime("%H:%M:%S.%f")[:-3]
            formatted.append(
                f"[{ts}] [{log.level}] [{log.node}] {log.message}")
        return "\n".join(formatted)

    def _build_prompt(self, logs: List[LogEntry]) -> str:
        """Build the analysis prompt."""
        log_text = self._format_logs_for_analysis(logs)

        return f"""Analyze the following robot log entries and identify any errors or issues:

```
{log_text}
```

Provide your analysis as a JSON object with this exact structure:
{{
    "severity": "critical|high|medium|low",
    "error_type": "Brief error classification",
    "root_cause": "Detailed explanation of the root cause",
    "affected_systems": ["node1", "node2", "subsystem"],
    "corrective_actions": ["Step 1", "Step 2", "Step 3"],
    "confidence": 0.95
}}

Respond ONLY with the JSON object, no additional text."""

    async def analyze(self, logs: List[LogEntry]) -> Optional[AnalysisResult]:
        """Analyze a list of log entries using OpenAI GPT."""
        if not logs:
            return None

        if not self.api_key:
            # Return a mock analysis for testing without API key
            return self._create_mock_analysis(logs)

        async with self._semaphore:
            self._stats["total_analyses"] += 1

            try:
                client = self._get_client()
                prompt = self._build_prompt(logs)

                response = await client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    timeout=settings.AI_TIMEOUT_SEC,
                )

                # Parse the response
                content = response.choices[0].message.content
                result = self._parse_response(content, logs)

                if result:
                    self._stats["successful_analyses"] += 1
                else:
                    self._stats["failed_analyses"] += 1

                return result

            except asyncio.TimeoutError:
                print("Analysis timed out")
                self._stats["failed_analyses"] += 1
                return self._create_fallback_analysis(logs, "Analysis timeout")
            except Exception as e:
                print(f"Unexpected error during analysis: {e}")
                self._stats["failed_analyses"] += 1
                return self._create_fallback_analysis(logs, str(e))

    def _parse_response(self, content: str, logs: List[LogEntry]) -> Optional[AnalysisResult]:
        """Parse the AI response into an AnalysisResult."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            data = json.loads(content)

            return AnalysisResult(
                id=f"analysis_{uuid.uuid4().hex[:8]}",
                timestamp=utc_now(),
                severity=data.get("severity", "medium"),
                error_type=data.get("error_type", "Unknown"),
                root_cause=data.get(
                    "root_cause", "Unable to determine root cause"),
                affected_systems=data.get("affected_systems", []),
                corrective_actions=data.get("corrective_actions", []),
                confidence=data.get("confidence", 0.5),
                context_logs=logs,
            )
        except json.JSONDecodeError as e:
            print(f"Failed to parse AI response as JSON: {e}")
            print(f"Response content: {content[:500]}")
            return None
        except Exception as e:
            print(f"Error parsing response: {e}")
            return None

    def _create_fallback_analysis(
        self,
        logs: List[LogEntry],
        error_message: str
    ) -> AnalysisResult:
        """Create a fallback analysis when AI fails."""
        # Find the most severe log entry
        error_logs = [log for log in logs if log.is_error()]
        primary_log = error_logs[0] if error_logs else logs[-1] if logs else None

        return AnalysisResult(
            id=f"analysis_{uuid.uuid4().hex[:8]}",
            timestamp=utc_now(),
            severity="high" if primary_log and primary_log.is_error() else "medium",
            error_type="Analysis Failed",
            root_cause=f"AI analysis failed: {error_message}. Manual review required.",
            affected_systems=[primary_log.node] if primary_log else [],
            corrective_actions=[
                "Review log entries manually",
                "Check system status",
                "Restart affected nodes if necessary",
            ],
            confidence=0.0,
            context_logs=logs,
        )

    def _create_mock_analysis(self, logs: List[LogEntry]) -> AnalysisResult:
        """Create a mock analysis for testing without API key."""
        error_logs = [log for log in logs if log.is_error()]
        primary_log = error_logs[0] if error_logs else logs[-1] if logs else None

        if primary_log:
            # Simple pattern matching for demo
            message = primary_log.message.lower()
            if "transform" in message:
                error_type = "Transform Timeout"
                root_cause = "TF tree not properly initialized or transform lookup timeout"
                actions = [
                    "Check TF tree with 'rosrun tf view_frames'",
                    "Restart static transform publisher",
                    "Verify frame IDs in configuration",
                ]
            elif "plan" in message or "path" in message:
                error_type = "Planning Failure"
                root_cause = "Navigation planner unable to find valid path to goal"
                actions = [
                    "Check costmap for obstacles",
                    "Verify goal is reachable",
                    "Adjust planner parameters",
                ]
            elif "sensor" in message or "laser" in message or "camera" in message:
                error_type = "Sensor Timeout"
                root_cause = "Sensor driver not publishing data or connection lost"
                actions = [
                    "Check sensor connections",
                    "Restart sensor driver node",
                    "Verify topic is being published",
                ]
            else:
                error_type = "System Error"
                root_cause = f"Error detected in {primary_log.node}: {primary_log.message}"
                actions = [
                    f"Review {primary_log.node} logs",
                    "Check node status with 'rosnode info'",
                    "Restart the affected node",
                ]

            return AnalysisResult(
                id=f"analysis_{uuid.uuid4().hex[:8]}",
                timestamp=utc_now(),
                severity="high",
                error_type=error_type,
                root_cause=root_cause,
                affected_systems=[primary_log.node],
                corrective_actions=actions,
                confidence=0.75,
                context_logs=logs,
                metadata={"mock": True},
            )

        return AnalysisResult(
            id=f"analysis_{uuid.uuid4().hex[:8]}",
            timestamp=utc_now(),
            severity="low",
            error_type="No Error Detected",
            root_cause="No errors found in provided logs",
            affected_systems=[],
            corrective_actions=["No action required"],
            confidence=0.9,
            context_logs=logs,
            metadata={"mock": True},
        )

    def get_stats(self) -> dict:
        """Get analysis statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset analysis statistics."""
        self._stats = {
            "total_analyses": 0,
            "successful_analyses": 0,
            "failed_analyses": 0,
        }


# For testing the analyzer directly
if __name__ == "__main__":
    from datetime import datetime

    async def main():
        analyzer = Analyzer()

        test_logs = [
            LogEntry(
                timestamp=datetime.now(),
                level="INFO",
                node="/move_base",
                message="Received goal",
                raw_line="[INFO] Received goal",
            ),
            LogEntry(
                timestamp=datetime.now(),
                level="WARN",
                node="/move_base",
                message="Waiting for transform",
                raw_line="[WARN] Waiting for transform",
            ),
            LogEntry(
                timestamp=datetime.now(),
                level="ERROR",
                node="/move_base",
                message="Failed to get robot pose: Transform timeout",
                raw_line="[ERROR] Failed to get robot pose: Transform timeout",
            ),
        ]

        result = await analyzer.analyze(test_logs)
        if result:
            print(json.dumps(result.to_dict(), indent=2, default=str))
        else:
            print("Analysis failed")

    asyncio.run(main())
