"""OpenAI API integration for coding analysis and vision explanations.

Implements:
- Structured vision-based coding problem analysis via GPT-4o
- JPEG screenshot encoding for bandwidth-efficient API calls
- PII/credential scrubbing before transmission
- Retry logic with exponential backoff for rate limits and transient errors
- Configurable timeouts and model selection via environment variables
- Local mock fallback when OPENAI_API_KEY is not configured
"""

import asyncio
import json
import os
import re
from typing import Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.common.schemas import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    CodingAnalysisResult,
    EdgeCase,
    current_utc_time,
)

logger = get_logger("Worker.AIEngine")

# ---------------------------------------------------------------------------
# PII / credential scrubbing
# ---------------------------------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9]{20,})\b"), "[API_KEY_REDACTED]"),
    (re.compile(r"\b(?:Bearer\s+[A-Za-z0-9._~+/=-]+)\b"), "[BEARER_TOKEN_REDACTED]"),
    (re.compile(r"\b(?:session[_-]?id|JSESSIONID|PHPSESSID|csrftoken)\s*[:=]\s*\S+", re.IGNORECASE), "[SESSION_REDACTED]"),
]


def scrub_pii(text: str) -> str:
    """Remove known PII patterns (emails, passwords, tokens) from text."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# System prompt for structured coding analysis
# ---------------------------------------------------------------------------
CODING_ANALYSIS_SYSTEM_PROMPT = """You are NIAT CodePilot, an expert educational coding assistant with computer vision capabilities.

TASK: Analyze the visible coding problem in the screenshot and produce a structured JSON analysis.

RULES:
- NEVER provide cheats, portal bypasses, or automated submission instructions.
- NEVER include passwords, session tokens, or personal information in your output.
- Always encourage deep algorithmic understanding.
- If the screenshot is unclear or partially obscured, say so in confidence_note.
- The student must review and approve everything before using it.

OUTPUT FORMAT — respond with ONLY a valid JSON object matching this schema:
{
  "problem_title": "Short title",
  "problem_description": "Full problem statement as visible",
  "programming_language": "Python",
  "constraints": ["constraint 1", "constraint 2"],
  "input_format": "Description of input format",
  "output_format": "Description of output format",
  "sample_inputs": ["sample input 1"],
  "sample_outputs": ["sample output 1"],
  "relevant_concepts": ["concept 1", "concept 2"],
  "step_by_step_explanation": ["Step 1: ...", "Step 2: ..."],
  "suggested_code": "def solve():\\n    pass",
  "code_explanation": "Line-by-line walkthrough",
  "edge_cases": [
    {"description": "Empty input", "example_input": "", "expected_behavior": "Return 0"}
  ],
  "confidence_note": "High confidence — full problem visible"
}

Respond with ONLY the JSON object. No markdown fences, no preamble, no commentary outside the JSON."""


# ---------------------------------------------------------------------------
# AI Engine Service
# ---------------------------------------------------------------------------
class AIEngineService:
    """Provides coding guidance and visual question explanation via OpenAI API.

    Handles:
    - Structured JSON vision analysis of coding problem screenshots
    - Free-text Q&A coding assistance
    - Automatic retry with exponential backoff for rate-limit and transient errors
    - PII scrubbing of all outbound prompts
    - Graceful local mock fallback when API key is not configured
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.provider = (provider or settings.ai_provider or "gemini").lower()

        # Resolve API key, model and base URL per provider
        if api_key is not None:
            self.api_key = api_key.strip().strip("'\"")
        elif self.provider == "gemini":
            self.api_key = (
                settings.gemini_api_key
                or os.getenv("GEMINI_API_KEY", "")
            ).strip().strip("'\"")
        else:
            self.api_key = (
                settings.openai_api_key
                or os.getenv("OPENAI_API_KEY", "")
            ).strip().strip("'\"")

        if self.provider == "gemini":
            self.base_url = (
                base_url
                or settings.gemini_base_url
                or "https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            self.model = model or settings.gemini_model or "gemini-flash-lite-latest"
        else:
            self.base_url = base_url or settings.openai_base_url or None
            self.model = model or settings.openai_model or "gpt-4o-mini"

        # Auto-detect key format if mismatched
        if self.api_key.startswith("AQ.") or self.api_key.startswith("AIzaSy"):
            self.provider = "gemini"
            if not base_url and not settings.gemini_base_url:
                self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            if not model and not settings.gemini_model:
                self.model = "gemini-flash-lite-latest"
        elif self.api_key.startswith("sk-") and self.provider != "openai":
            self.provider = "openai"
            if not model:
                self.model = "gpt-4o-mini"

        self.max_tokens = settings.openai_max_tokens
        self.timeout = settings.openai_timeout_seconds
        self.max_retries = settings.openai_max_retries
        self._client = None

        if self.api_key:
            try:
                from openai import AsyncOpenAI

                client_kwargs = {
                    "api_key": self.api_key,
                    "timeout": self.timeout,
                    "max_retries": 0,  # Handled in _call_openai_with_retry
                }
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url

                self._client = AsyncOpenAI(**client_kwargs)
                logger.info(
                    f"{self.provider.upper()} AI service initialized with model '{self.model}'."
                )
            except Exception as e:
                logger.warning(f"Could not initialize {self.provider} client: {e}")
        else:
            logger.info(
                f"{self.provider.upper()}_API_KEY not configured. AI engine will operate in local mock/guidance mode."
            )

    @property
    def is_configured(self) -> bool:
        """Whether the OpenAI API client is ready."""
        return self._client is not None

    # ------------------------------------------------------------------
    # Core API call with retry logic
    # ------------------------------------------------------------------
    async def _call_openai_with_retry(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Execute an OpenAI chat completion with exponential-backoff retry.

        Handles:
        - RateLimitError  → exponential backoff (2^attempt seconds, max 32s)
        - APITimeoutError → retry with same backoff
        - APIConnectionError → retry with same backoff
        - Other APIError  → raise immediately
        """
        from openai import (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            APIStatusError,
        )

        tokens = max_tokens or self.max_tokens
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=tokens,
                )
                content = response.choices[0].message.content
                if content is None:
                    raise RuntimeError("AI service returned an empty response body.")
                # Strip internal reasoning tokens if present
                if "<thought>" in content and "</thought>" in content:
                    content = re.sub(r"<thought>.*?</thought>", "", content, flags=re.DOTALL)
                return content.strip()

            except RateLimitError as e:
                # Quota exhaustion errors should not be retried indefinitely
                err_msg = str(e).lower()
                if "quota" in err_msg or "credit" in err_msg:
                    logger.error("AI API quota exhausted.")
                    raise RuntimeError(f"AI API quota exhausted: {e.message}") from e

                wait = min(2 ** attempt, 32)
                logger.warning(
                    f"Rate limited by AI provider (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {wait}s..."
                )
                last_error = e
                await asyncio.sleep(wait)

            except APITimeoutError as e:
                wait = min(2 ** attempt, 32)
                logger.warning(
                    f"AI API timeout (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {wait}s..."
                )
                last_error = e
                await asyncio.sleep(wait)

            except APIConnectionError as e:
                wait = min(2 ** attempt, 32)
                logger.warning(
                    f"AI API connection error (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {wait}s..."
                )
                last_error = e
                await asyncio.sleep(wait)

            except APIStatusError as e:
                if e.status_code == 404:
                    logger.error(f"Invalid AI model '{self.model}'.")
                    raise RuntimeError(
                        f"Invalid AI model '{self.model}': Model not found or unavailable for this provider."
                    ) from e

                # Retry transient server errors (500, 502, 503, 504) and rate limits (429)
                if e.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    wait = min(2 ** attempt, 32)
                    logger.warning(
                        f"Transient AI API error ({e.status_code}) on attempt {attempt + 1}/{self.max_retries}. "
                        f"Retrying in {wait}s..."
                    )
                    last_error = e
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"AI API error (status {e.status_code})")
                    raise RuntimeError(f"AI API error ({e.status_code}): {e.message}") from e

        if isinstance(last_error, APITimeoutError):
            raise RuntimeError(
                f"AI API request timed out after {self.timeout}s and {self.max_retries} attempts."
            )
        if isinstance(last_error, APIConnectionError):
            raise RuntimeError(
                f"AI API network connection failed after {self.max_retries} attempts. Check your internet connection."
            )
        raise RuntimeError(
            f"AI API call failed after {self.max_retries} retries: {last_error}"
        )

    # ------------------------------------------------------------------
    # Structured coding analysis via vision
    # ------------------------------------------------------------------
    async def analyze_screen(
        self,
        image_base64: str,
        worker_id: str,
        additional_prompt: str = "",
        image_format: str = "jpeg",
    ) -> CodingAnalysisResult:
        """Analyze a screenshot of a coding problem and return structured results.

        Args:
            image_base64: Base64-encoded JPEG or PNG screenshot.
            worker_id: Identifier of the requesting worker.
            additional_prompt: Optional extra question or context from the student.
            image_format: Image MIME subtype ('jpeg' or 'png').

        Returns:
            CodingAnalysisResult with structured problem breakdown.

        Raises:
            PermissionError: If the OpenAI client is not configured.
            RuntimeError: On API failures after retries.
        """
        if not image_base64 or not isinstance(image_base64, str):
            raise ValueError("Unsupported image input: image_base64 must be a non-empty base64 string.")

        normalized_format = image_format.lower().lstrip(".")
        if normalized_format in ("jpg", "jpeg"):
            mime_subtype = "jpeg"
        elif normalized_format == "png":
            mime_subtype = "png"
        elif normalized_format == "webp":
            mime_subtype = "webp"
        else:
            raise ValueError(f"Unsupported image format '{image_format}'. Supported formats: jpeg, png, webp.")

        user_text = (
            "Analyze the coding problem visible in this screenshot. "
            "Return a structured JSON analysis following the schema in your instructions."
        )
        if additional_prompt:
            user_text += f"\n\nAdditional student question: {scrub_pii(additional_prompt)}"

        if self._client:
            messages = [
                {"role": "system", "content": CODING_ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{mime_subtype};base64,{image_base64}",
                            },
                        },
                    ],
                },
            ]

            raw_content = await self._call_openai_with_retry(messages)
            return self._parse_analysis_json(raw_content)

        # Local mock fallback with provider-aware guidance
        return self._build_mock_analysis(worker_id, additional_prompt, provider=self.provider)

    # ------------------------------------------------------------------
    # Legacy free-text analysis (kept for backward compatibility)
    # ------------------------------------------------------------------
    async def analyze_coding_problem(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """Analyze a coding problem with optional screenshot context.

        Safety guard: All outputs strictly require explicit student review.
        """
        if not request.explicit_student_approval:
            raise PermissionError(
                "Student approval and consent is required before transmitting screenshot for AI analysis."
            )

        system_prompt = (
            "You are NIAT CodePilot, an intelligent educational coding assistant. "
            "Your mission is to guide students with clear explanations, algorithmic intuition, "
            "and clean code examples. Never provide raw bypasses, cheats, or automated submissions. "
            "Always encourage deep understanding."
        )

        if self._client:
            messages = [{"role": "system", "content": system_prompt}]
            user_content = [{"type": "text", "text": scrub_pii(request.prompt)}]

            if request.image_base64:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{request.image_base64}",
                        },
                    }
                )

            messages.append({"role": "user", "content": user_content})

            content = await self._call_openai_with_retry(messages)
            return AIAnalysisResponse(
                worker_id=request.worker_id,
                explanation=content,
                requires_student_review=True,
                auto_submission_permitted=False,
                analyzed_at=current_utc_time(),
            )

        # Fallback local guidance when API key is not yet set
        key_name = "GEMINI_API_KEY" if self.provider == "gemini" else "OPENAI_API_KEY"
        return AIAnalysisResponse(
            worker_id=request.worker_id,
            explanation=(
                f"[Local Simulation Engine]: Analysis for question '{request.prompt}'. "
                f"To connect live {self.provider.title()} vision analysis, provide {key_name} in your .env file."
            ),
            suggested_code="# Suggested template:\ndef solve_problem():\n    pass\n",
            requires_student_review=True,
            auto_submission_permitted=False,
            analyzed_at=current_utc_time(),
        )

    # ------------------------------------------------------------------
    # JSON parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_analysis_json(raw: str) -> CodingAnalysisResult:
        """Parse OpenAI JSON response into a CodingAnalysisResult.

        Handles common LLM quirks: markdown code fences, trailing commas, etc.
        """
        cleaned = raw.strip()
        # Strip optional markdown ```json ... ``` fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: treat entire raw output as a plain-text explanation
            logger.warning("Failed to parse structured JSON from AI response; using raw text.")
            return CodingAnalysisResult(
                problem_title="Analysis Result",
                problem_description=raw.strip(),
                step_by_step_explanation=[raw.strip()],
                confidence_note="Response was not structured JSON; displayed as plain text.",
            )

        # Normalize edge_cases from dicts to EdgeCase models if needed
        if "edge_cases" in data and isinstance(data["edge_cases"], list):
            normalized = []
            for ec in data["edge_cases"]:
                if isinstance(ec, dict):
                    normalized.append(EdgeCase(**ec))
                elif isinstance(ec, str):
                    normalized.append(EdgeCase(description=ec))
            data["edge_cases"] = normalized

        # Enforce safety invariants regardless of what the model returns
        data["requires_student_review"] = True
        data["auto_submission_permitted"] = False

        return CodingAnalysisResult(**data)

    @staticmethod
    def _build_mock_analysis(
        worker_id: str, prompt: str = "", provider: str = "gemini"
    ) -> CodingAnalysisResult:
        """Build a mock CodingAnalysisResult for local testing when API key is not configured."""
        if provider == "gemini":
            title = "[Mock] Gemini Vision Analysis"
            desc = (
                "GEMINI_API_KEY is not configured in your .env file. This is a simulated analysis response.\n"
                "To enable live Gemini multimodal vision analysis, add your GEMINI_API_KEY to the .env file."
            )
            concepts = ["Configure GEMINI_API_KEY", "Gemini Multimodal Vision API"]
            steps = [
                "Step 1: Open your project-root .env file",
                "Step 2: Set GEMINI_API_KEY=your-gemini-key",
                "Step 3: Ensure AI_PROVIDER=gemini",
                "Step 4: Restart the worker application and click 'Analyze Screen'",
            ]
            code = (
                "# Configure your .env file:\n"
                "# AI_PROVIDER=gemini\n"
                "# GEMINI_API_KEY=your-gemini-key\n"
                "# GEMINI_MODEL=gemini-flash-lite-latest\n"
            )
            explanation = "Set the GEMINI_API_KEY environment variable to enable live Gemini analysis."
            key_name = "GEMINI_API_KEY"
        elif provider == "openai":
            title = "[Mock] OpenAI Vision Analysis"
            desc = (
                "OPENAI_API_KEY is not configured in your .env file. This is a simulated analysis response.\n"
                "To enable live AI-powered screen analysis, add your OpenAI API key to the .env file."
            )
            concepts = ["Configure OPENAI_API_KEY", "OpenAI Vision API integration"]
            steps = [
                "Step 1: Open your project-root .env file",
                "Step 2: Set OPENAI_API_KEY=sk-...",
                "Step 3: Ensure AI_PROVIDER=openai",
                "Step 4: Restart the worker application and click 'Analyze Screen'",
            ]
            code = (
                "# Configure your .env file:\n"
                "# AI_PROVIDER=openai\n"
                "# OPENAI_API_KEY=sk-your-key-here\n"
                "# OPENAI_MODEL=gpt-4o-mini\n"
            )
            explanation = "Set the OPENAI_API_KEY environment variable to enable live AI analysis."
            key_name = "OPENAI_API_KEY"
        else:
            title = "[Configuration Error] AI Provider Not Configured"
            desc = (
                f"Provider '{provider}' is not configured or unsupported.\n"
                "Please configure AI_PROVIDER (gemini or openai) and the corresponding API key in your .env file."
            )
            concepts = ["Configure AI_PROVIDER", "Configure API Key"]
            steps = [
                "Step 1: Set AI_PROVIDER=gemini in .env",
                "Step 2: Set GEMINI_API_KEY=your-key in .env",
                "Step 3: Restart worker",
            ]
            code = "# Set AI_PROVIDER=gemini\n# GEMINI_API_KEY=your-key\n"
            explanation = "Configure valid AI provider credentials."
            key_name = "AI_API_KEY"

        return CodingAnalysisResult(
            problem_title=title,
            problem_description=desc,
            programming_language="Python",
            relevant_concepts=concepts,
            step_by_step_explanation=steps,
            suggested_code=code,
            code_explanation=explanation,
            edge_cases=[
                EdgeCase(
                    description=f"No {key_name} configured",
                    example_input=f"{key_name}=",
                    expected_behavior="Falls back to this provider-aware mock response",
                )
            ],
            confidence_note=f"Mock response for provider '{provider}' — no live API call was made.",
        )
