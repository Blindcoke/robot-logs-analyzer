"""
Taxonomy classifier: maps analysis results to SKILL.md categories using OpenAI.
"""
import json
import asyncio
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from models import AnalysisResult, TaxonomyClassification
from config import settings

# Load SKILL.md content once
_SKILL_PATH = Path(__file__).parent / "SKILL.md"


def _load_skill_content() -> str:
    """Load SKILL.md content for the prompt."""
    if _SKILL_PATH.exists():
        return _SKILL_PATH.read_text(encoding="utf-8")
    return ""


SYSTEM_PROMPT = """You are an expert at classifying errors for a log analyzer. Use the taxonomy below to assign exactly one category and optional event/error_code/component/dependency.

Categories (pick exactly one): INFRASTRUCTURE, QUEUE, AUTH, PERFORMANCE, EXTERNAL, APPLICATION.

Severity (use the one from the input or map: critical->CRITICAL, high->HIGH, medium->MEDIUM, low->LOW).

Output JSON only:
{"category": "CATEGORY", "event": "EVENT_NAME", "error_code": "CODE", "component": "component-name", "dependency": "dependency-name"}
Use null for optional fields you cannot infer. event and error_code should be UPPER_SNAKE_CASE (e.g. DB_TIMEOUT, QUEUE_OVERFLOW)."""


class TaxonomyClassifier:
    """Classifies AnalysisResult into SKILL.md taxonomy using OpenAI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self.temperature = temperature
        self._client: Optional[AsyncOpenAI] = None
        self._skill_content = _load_skill_content()

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                raise ValueError("OpenAI API key not configured")
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    def _build_prompt(self, result: AnalysisResult) -> str:
        skill = self._skill_content or "Categories: INFRASTRUCTURE, QUEUE, AUTH, PERFORMANCE, EXTERNAL, APPLICATION."
        return f"""Taxonomy reference:
{skill}

Classify this analysis result into the taxonomy above.

Input:
- error_type: {result.error_type}
- severity: {result.severity}
- root_cause: {result.root_cause[:500]}
- affected_systems: {result.affected_systems}

Respond with a single JSON object: {{"category": "...", "event": "...", "error_code": "...", "component": "...", "dependency": "..."}}
Use null for unknown optional fields. category must be one of: INFRASTRUCTURE, QUEUE, AUTH, PERFORMANCE, EXTERNAL, APPLICATION."""

    async def classify(self, result: AnalysisResult) -> Optional[TaxonomyClassification]:
        """Classify an analysis result into SKILL taxonomy. Returns None if API unavailable or parse error."""
        if not self.api_key:
            return self._fallback_classify(result)

        try:
            client = self._get_client()
            prompt = self._build_prompt(result)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.model,
                    max_tokens=256,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=settings.AI_TIMEOUT_SEC,
            )
            content = response.choices[0].message.content or ""
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
            data = json.loads(content)
            category = (data.get("category") or "APPLICATION").upper()
            if category not in (
                "INFRASTRUCTURE",
                "QUEUE",
                "AUTH",
                "PERFORMANCE",
                "EXTERNAL",
                "APPLICATION",
            ):
                category = "APPLICATION"
            return TaxonomyClassification(
                category=category,
                event=data.get("event"),
                error_code=data.get("error_code"),
                component=data.get("component"),
                dependency=data.get("dependency"),
            )
        except (asyncio.TimeoutError, json.JSONDecodeError, KeyError, Exception) as e:
            print(f"[Classifier] Fallback due to: {e}")
            return self._fallback_classify(result)

    def _fallback_classify(self, result: AnalysisResult) -> TaxonomyClassification:
        """Rule-based fallback when OpenAI is not available."""
        msg = (result.error_type + " " + result.root_cause).lower()
        if "transform" in msg or "tf" in msg or "timeout" in msg:
            category = "INFRASTRUCTURE"
            event = "CONNECTION_TIMEOUT"
        elif "plan" in msg or "path" in msg or "navigation" in msg:
            category = "APPLICATION"
            event = "PLANNING_FAILURE"
        elif "sensor" in msg or "laser" in msg or "camera" in msg:
            category = "EXTERNAL"
            event = "SENSOR_TIMEOUT"
        elif "joint" in msg or "limit" in msg:
            category = "APPLICATION"
            event = "JOINT_LIMIT"
        elif "connection" in msg or "hardware" in msg:
            category = "INFRASTRUCTURE"
            event = "CONNECTION_TIMEOUT"
        elif "collision" in msg:
            category = "APPLICATION"
            event = "COLLISION_DETECTED"
        else:
            category = "APPLICATION"
            event = "APPLICATION_ERROR"
        return TaxonomyClassification(
            category=category,
            event=event,
            error_code=event,
            component="robot-system",
            dependency=None,
        )
