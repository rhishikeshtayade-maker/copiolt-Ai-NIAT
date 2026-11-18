"""Unit tests for the AI engine service with mocked OpenAI API responses."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.common.schemas import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    CodingAnalysisResult,
    EdgeCase,
)
from src.worker.ai_engine import AIEngineService, scrub_pii, CODING_ANALYSIS_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# PII scrubbing tests
# ---------------------------------------------------------------------------
class TestPIIScrubbing:
    def test_scrub_email(self):
        assert "EMAIL_REDACTED" in scrub_pii("Contact admin@example.com for details")

    def test_scrub_password(self):
        assert "CREDENTIAL_REDACTED" in scrub_pii("password: my_secret_password123")
        assert "CREDENTIAL_REDACTED" in scrub_pii("api_key=sk-abc123xyz")

    def test_scrub_bearer_token(self):
        assert "BEARER_TOKEN_REDACTED" in scrub_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test")

    def test_scrub_session_token(self):
        assert "SESSION_REDACTED" in scrub_pii("session_id=abc123xyz789")
        assert "SESSION_REDACTED" in scrub_pii("JSESSIONID=node0abc123")

    def test_scrub_openai_key(self):
        assert "API_KEY_REDACTED" in scrub_pii("My key is sk-proj1234567890abcdefghij")

    def test_clean_text_unchanged(self):
        clean = "Write a function that returns the sum of two numbers."
        assert scrub_pii(clean) == clean


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------
class TestJSONParsing:
    def test_parse_valid_json(self):
        raw = json.dumps({
            "problem_title": "Two Sum",
            "problem_description": "Find two numbers that add up to target.",
            "programming_language": "Python",
            "constraints": ["1 <= nums.length <= 10^4"],
            "input_format": "Array of integers and a target",
            "output_format": "Indices of the two numbers",
            "sample_inputs": ["[2,7,11,15], target=9"],
            "sample_outputs": ["[0,1]"],
            "relevant_concepts": ["Hash Map", "Two Pointers"],
            "step_by_step_explanation": [
                "Step 1: Create a hash map",
                "Step 2: For each number, check complement",
            ],
            "suggested_code": "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i",
            "code_explanation": "Use a dictionary to store seen values and their indices.",
            "edge_cases": [
                {"description": "Single element", "example_input": "[1]", "expected_behavior": "No solution"},
                {"description": "Duplicate values", "example_input": "[3,3], target=6", "expected_behavior": "[0,1]"},
            ],
            "confidence_note": "High confidence — full problem visible",
        })

        result = AIEngineService._parse_analysis_json(raw)
        assert isinstance(result, CodingAnalysisResult)
        assert result.problem_title == "Two Sum"
        assert result.programming_language == "Python"
        assert len(result.constraints) == 1
        assert len(result.relevant_concepts) == 2
        assert len(result.step_by_step_explanation) == 2
        assert result.suggested_code is not None
        assert "two_sum" in result.suggested_code
        assert len(result.edge_cases) == 2
        assert isinstance(result.edge_cases[0], EdgeCase)
        assert result.confidence_note == "High confidence — full problem visible"
        # Safety invariants always enforced
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False

    def test_parse_json_with_markdown_fences(self):
        raw = '```json\n{"problem_title": "Fenced", "problem_description": "Test"}\n```'
        result = AIEngineService._parse_analysis_json(raw)
        assert result.problem_title == "Fenced"

    def test_parse_invalid_json_fallback(self):
        raw = "This is not JSON at all, just a plain explanation."
        result = AIEngineService._parse_analysis_json(raw)
        assert result.problem_title == "Analysis Result"
        assert "not structured JSON" in result.confidence_note

    def test_edge_cases_as_strings(self):
        raw = json.dumps({
            "problem_title": "String edges",
            "edge_cases": ["empty input", "very large input"],
        })
        result = AIEngineService._parse_analysis_json(raw)
        assert len(result.edge_cases) == 2
        assert result.edge_cases[0].description == "empty input"

    def test_safety_flags_cannot_be_overridden(self):
        """Even if the model returns auto_submission_permitted=True, we force it False."""
        raw = json.dumps({
            "problem_title": "Tampered",
            "auto_submission_permitted": True,
            "requires_student_review": False,
        })
        result = AIEngineService._parse_analysis_json(raw)
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False


# ---------------------------------------------------------------------------
# Mock fallback tests (no API key)
# ---------------------------------------------------------------------------
class TestMockFallback:
    def test_mock_analysis_without_api_key(self):
        result = AIEngineService._build_mock_analysis("worker-01", "explain recursion")
        assert isinstance(result, CodingAnalysisResult)
        assert "[Mock]" in result.problem_title
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False
        assert len(result.step_by_step_explanation) > 0

    def test_engine_not_configured_returns_mock(self):
        """When OPENAI_API_KEY is empty, is_configured should be False."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            engine = AIEngineService(api_key="")
            assert engine.is_configured is False


# ---------------------------------------------------------------------------
# Mocked OpenAI API call tests
# ---------------------------------------------------------------------------
MOCK_STRUCTURED_RESPONSE = json.dumps({
    "problem_title": "Fibonacci Sequence",
    "problem_description": "Write a function to compute the nth Fibonacci number.",
    "programming_language": "Python",
    "constraints": ["0 <= n <= 30"],
    "input_format": "A single integer n",
    "output_format": "The nth Fibonacci number",
    "sample_inputs": ["5"],
    "sample_outputs": ["5"],
    "relevant_concepts": ["Dynamic Programming", "Recursion", "Memoization"],
    "step_by_step_explanation": [
        "Step 1: Base cases: fib(0) = 0, fib(1) = 1",
        "Step 2: Use bottom-up DP to build from base cases",
        "Step 3: Return fib(n)",
    ],
    "suggested_code": "def fib(n):\n    if n <= 1:\n        return n\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b",
    "code_explanation": "Iterative bottom-up approach with O(n) time and O(1) space.",
    "edge_cases": [
        {"description": "n=0", "example_input": "0", "expected_behavior": "0"},
        {"description": "n=1", "example_input": "1", "expected_behavior": "1"},
    ],
    "confidence_note": "High confidence",
})


def _make_mock_openai_response(content: str):
    """Create a mock OpenAI ChatCompletion response object."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


class TestMockedAPICalls:
    @pytest.mark.asyncio
    async def test_analyze_screen_structured(self):
        """Test full analyze_screen pipeline with mocked OpenAI completion."""
        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")

        mock_create = AsyncMock(return_value=_make_mock_openai_response(MOCK_STRUCTURED_RESPONSE))
        engine._client = MagicMock()
        engine._client.chat = MagicMock()
        engine._client.chat.completions = MagicMock()
        engine._client.chat.completions.create = mock_create

        result = await engine.analyze_screen(
            image_base64="AAAA",
            worker_id="worker-test",
            additional_prompt="Explain time complexity",
        )

        assert isinstance(result, CodingAnalysisResult)
        assert result.problem_title == "Fibonacci Sequence"
        assert result.programming_language == "Python"
        assert "Dynamic Programming" in result.relevant_concepts
        assert len(result.step_by_step_explanation) == 3
        assert "fib" in result.suggested_code
        assert len(result.edge_cases) == 2
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False

        # Verify the API was called with correct structure
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages") or call_kwargs[0][0] if call_kwargs[0] else None
        if messages is None:
            # Might be positional or keyword
            messages = call_kwargs.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # User message should contain both text and image_url
        user_content = messages[1]["content"]
        assert any(c["type"] == "text" for c in user_content)
        assert any(c["type"] == "image_url" for c in user_content)

    @pytest.mark.asyncio
    async def test_analyze_screen_pii_scrubbing(self):
        """Verify that PII in the additional prompt is scrubbed before API call."""
        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")

        mock_create = AsyncMock(return_value=_make_mock_openai_response(MOCK_STRUCTURED_RESPONSE))
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        await engine.analyze_screen(
            image_base64="AAAA",
            worker_id="worker-test",
            additional_prompt="My password: secret123 and email is user@example.com",
        )

        call_kwargs = mock_create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        user_text = messages[1]["content"][0]["text"]
        assert "secret123" not in user_text
        assert "user@example.com" not in user_text
        assert "CREDENTIAL_REDACTED" in user_text
        assert "EMAIL_REDACTED" in user_text

    @pytest.mark.asyncio
    async def test_analyze_coding_problem_legacy(self):
        """Test the legacy analyze_coding_problem method with mock."""
        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")

        mock_create = AsyncMock(
            return_value=_make_mock_openai_response("Here is the explanation.")
        )
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        request = AIAnalysisRequest(
            worker_id="worker-test",
            prompt="Explain binary search",
            explicit_student_approval=True,
        )

        result = await engine.analyze_coding_problem(request)
        assert isinstance(result, AIAnalysisResponse)
        assert result.explanation == "Here is the explanation."
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False

    @pytest.mark.asyncio
    async def test_analyze_coding_problem_no_consent_raises(self):
        """Verify PermissionError when student approval is missing."""
        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")

        request = AIAnalysisRequest(
            worker_id="worker-test",
            prompt="Explain something",
            explicit_student_approval=False,
        )

        with pytest.raises(PermissionError) as exc_info:
            await engine.analyze_coding_problem(request)
        assert "Student approval" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self):
        """Verify exponential backoff retry on rate-limit errors."""
        from openai import RateLimitError
        import httpx

        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")
        engine.max_retries = 3

        # Create a proper RateLimitError
        mock_response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        rate_error = RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        # Fail twice with rate limit, then succeed
        mock_create = AsyncMock(
            side_effect=[
                rate_error,
                rate_error,
                _make_mock_openai_response("Success after retries"),
            ]
        )
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        # Patch asyncio.sleep to avoid actual delays in tests
        with patch("src.worker.ai_engine.asyncio.sleep", new_callable=AsyncMock):
            content = await engine._call_openai_with_retry(
                messages=[{"role": "user", "content": "test"}]
            )

        assert content == "Success after retries"
        assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises(self):
        """Verify RuntimeError when all retries are exhausted."""
        from openai import RateLimitError
        import httpx

        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")
        engine.max_retries = 2

        mock_response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        rate_error = RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        mock_create = AsyncMock(side_effect=rate_error)
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with patch("src.worker.ai_engine.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="failed after 2 retries"):
                await engine._call_openai_with_retry(
                    messages=[{"role": "user", "content": "test"}]
                )

    @pytest.mark.asyncio
    async def test_api_status_error_no_retry(self):
        """Non-retryable API errors (e.g. 401 auth) should raise immediately."""
        from openai import AuthenticationError
        import httpx

        engine = AIEngineService(api_key="sk-test-key-00000000000000000000")
        engine.max_retries = 3

        mock_response = httpx.Response(
            status_code=401,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        auth_error = AuthenticationError(
            message="Invalid API key",
            response=mock_response,
            body={"error": {"message": "Invalid API key"}},
        )

        mock_create = AsyncMock(side_effect=auth_error)
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with pytest.raises(RuntimeError, match="401"):
            await engine._call_openai_with_retry(
                messages=[{"role": "user", "content": "test"}]
            )

        # Should fail immediately, no retries
        assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_analyze_screen_fallback_without_client(self):
        """When API key is empty, analyze_screen returns mock result."""
        engine = AIEngineService(api_key="")
        result = await engine.analyze_screen(
            image_base64="AAAA",
            worker_id="worker-no-key",
        )
        assert isinstance(result, CodingAnalysisResult)
        assert "[Mock]" in result.problem_title
        assert result.requires_student_review is True


# ---------------------------------------------------------------------------
# Capture JPEG integration test
# ---------------------------------------------------------------------------
class TestCaptureJPEGBase64:
    def test_jpeg_capture_with_mock(self):
        """Verify JPEG base64 output from capture service."""
        from src.worker.capture import ScreenCaptureService

        service = ScreenCaptureService(worker_id="test-worker")
        service.set_user_permission(True)
        service.start()

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct
        mock_sct.monitors = [{"left": 0, "top": 0, "width": 640, "height": 480}]
        mock_frame = MagicMock()
        mock_frame.width = 640
        mock_frame.height = 480
        mock_frame.rgb = b"\x80" * (640 * 480 * 3)
        mock_sct.grab.return_value = mock_frame

        with patch("mss.mss", return_value=mock_sct):
            b64_str, meta = service.capture_jpeg_base64(monitor_index=0, quality=50)

        assert isinstance(b64_str, str)
        assert len(b64_str) > 0
        assert meta.format == "JPEG"
        assert meta.explicit_permission_verified is True
        assert meta.frame_size_bytes > 0

        # Verify it is valid base64 that decodes to JPEG
        import base64
        raw_bytes = base64.b64decode(b64_str)
        assert raw_bytes[:2] == b"\xff\xd8"  # JPEG magic bytes

    def test_jpeg_capture_requires_permission(self):
        """JPEG capture must also enforce consent."""
        from src.worker.capture import ScreenCaptureService

        service = ScreenCaptureService(worker_id="test-worker")
        with pytest.raises(PermissionError):
            service.capture_jpeg_base64()


# ---------------------------------------------------------------------------
# CodingAnalysisResult schema tests
# ---------------------------------------------------------------------------
class TestCodingAnalysisResultSchema:
    def test_default_safety_flags(self):
        result = CodingAnalysisResult()
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False
        assert result.problem_title == "Untitled Problem"

    def test_full_construction(self):
        result = CodingAnalysisResult(
            problem_title="Sort Array",
            problem_description="Sort an integer array in ascending order.",
            programming_language="Python",
            constraints=["1 <= len(arr) <= 1000"],
            input_format="Array of integers",
            output_format="Sorted array",
            sample_inputs=["[3,1,2]"],
            sample_outputs=["[1,2,3]"],
            relevant_concepts=["Sorting", "Comparison"],
            step_by_step_explanation=["Step 1: Use built-in sort"],
            suggested_code="arr.sort()",
            code_explanation="In-place sort using Timsort.",
            edge_cases=[EdgeCase(description="Empty array", expected_behavior="[]")],
            confidence_note="High",
        )
        assert result.problem_title == "Sort Array"
        assert len(result.edge_cases) == 1
        assert result.edge_cases[0].description == "Empty array"


# ---------------------------------------------------------------------------
# Error handling and validation tests
# ---------------------------------------------------------------------------
class TestErrorHandlingAndValidation:
    @pytest.mark.asyncio
    async def test_unsupported_image_input_empty(self):
        engine = AIEngineService(api_key="test-key")
        with pytest.raises(ValueError, match="Unsupported image input"):
            await engine.analyze_screen(image_base64="", worker_id="w1")

    @pytest.mark.asyncio
    async def test_unsupported_image_format(self):
        engine = AIEngineService(api_key="test-key")
        with pytest.raises(ValueError, match="Unsupported image format"):
            await engine.analyze_screen(image_base64="AAAA", worker_id="w1", image_format="bmp")

    @pytest.mark.asyncio
    async def test_invalid_model_error_handling(self):
        from openai import NotFoundError
        import httpx

        engine = AIEngineService(api_key="test-key", model="nonexistent-model")
        mock_resp = httpx.Response(404, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"))
        mock_create = AsyncMock(side_effect=NotFoundError("Model not found", response=mock_resp, body={}))
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with pytest.raises(RuntimeError, match="Invalid AI model"):
            await engine.analyze_screen(image_base64="AAAA", worker_id="w1")

    @pytest.mark.asyncio
    async def test_quota_exhaustion_error_handling(self):
        from openai import RateLimitError
        import httpx

        engine = AIEngineService(api_key="test-key")
        mock_resp = httpx.Response(429, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"))
        mock_create = AsyncMock(side_effect=RateLimitError("You have no credits remaining. Add quota to continue.", response=mock_resp, body={}))
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with pytest.raises(RuntimeError, match="quota exhausted"):
            await engine.analyze_screen(image_base64="AAAA", worker_id="w1")

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        from openai import APITimeoutError
        import httpx

        engine = AIEngineService(api_key="test-key")
        engine.max_retries = 1
        req = httpx.Request("POST", "https://generativelanguage.googleapis.com")
        mock_create = AsyncMock(side_effect=APITimeoutError(request=req))
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with pytest.raises(RuntimeError, match="timed out"):
            await engine.analyze_screen(image_base64="AAAA", worker_id="w1")

    @pytest.mark.asyncio
    async def test_network_connection_error_handling(self):
        from openai import APIConnectionError
        import httpx

        engine = AIEngineService(api_key="test-key")
        engine.max_retries = 1
        req = httpx.Request("POST", "https://generativelanguage.googleapis.com")
        mock_create = AsyncMock(side_effect=APIConnectionError(request=req, message="Connection refused"))
        engine._client = MagicMock()
        engine._client.chat.completions.create = mock_create

        with pytest.raises(RuntimeError, match="network connection failed"):
            await engine.analyze_screen(image_base64="AAAA", worker_id="w1")


# ---------------------------------------------------------------------------
# Real Synthetic Screenshot Integration Test
# ---------------------------------------------------------------------------
class TestGeminiVisionRealIntegration:
    @pytest.mark.asyncio
    async def test_real_screenshot_interpretation_with_gemini(self):
        """End-to-end integration test:
        Renders a synthetic screenshot containing a coding problem, encodes it as a JPEG
        data URL, transmits it to Gemini, and validates the structured Pydantic response.
        """
        import base64
        import io
        from PIL import Image, ImageDraw

        # 1. Render synthetic coding screenshot
        img = Image.new("RGB", (650, 240), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        lines = [
            "Problem: Reverse a String",
            "Description: Given an input string s, reverse the characters in-place.",
            "Input: s = 'hello'",
            "Output: 'olleh'",
            "Constraints: 1 <= s.length <= 10^5",
        ]
        y = 20
        for line in lines:
            d.text((25, y), line, fill=(0, 0, 0))
            y += 35

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64_jpeg = base64.b64encode(buf.getvalue()).decode("utf-8")

        # 2. Initialize engine with configured Gemini model
        engine = AIEngineService(model="gemini-flash-lite-latest")
        if not engine.is_configured:
            pytest.skip("GEMINI_API_KEY is not configured in environment. Skipping live Gemini vision test.")

        # 3. Analyze screen
        result = await engine.analyze_screen(
            image_base64=b64_jpeg,
            worker_id="integration-worker",
            additional_prompt="Identify the algorithmic approach and explain it clearly",
            image_format="jpeg",
        )

        # 4. Validate with Pydantic model
        assert isinstance(result, CodingAnalysisResult)
        assert len(result.problem_title) > 0
        assert "reverse" in result.problem_title.lower() or "string" in result.problem_title.lower()
        assert len(result.step_by_step_explanation) > 0
        assert result.suggested_code is not None and len(result.suggested_code) > 0
        assert result.requires_student_review is True
        assert result.auto_submission_permitted is False


class TestProviderAwareness:
    def test_gemini_provider_mock_message(self):
        """When AI_PROVIDER is gemini but no key is set, mock guidance must cite GEMINI_API_KEY."""
        engine = AIEngineService(api_key="", provider="gemini")
        assert engine.is_configured is False
        mock = engine._build_mock_analysis("w1", "test prompt", provider="gemini")
        assert "GEMINI_API_KEY is not configured in your .env file" in mock.problem_description
        assert "OPENAI_API_KEY" not in mock.problem_description
        assert "GEMINI_API_KEY=your-gemini-key" in mock.suggested_code

    def test_openai_provider_mock_message(self):
        """When AI_PROVIDER is openai but no key is set, mock guidance must cite OPENAI_API_KEY."""
        engine = AIEngineService(api_key="", provider="openai")
        assert engine.is_configured is False
        mock = engine._build_mock_analysis("w1", "test prompt", provider="openai")
        assert "OPENAI_API_KEY is not configured" in mock.problem_description
        assert "GEMINI_API_KEY" not in mock.problem_description

    def test_unconfigured_provider_error_message(self):
        """When provider is unconfigured or invalid, show a clear configuration error."""
        engine = AIEngineService(api_key="", provider="unknown_provider")
        assert engine.is_configured is False
        mock = engine._build_mock_analysis("w1", "test prompt", provider="unknown_provider")
        assert "[Configuration Error] AI Provider Not Configured" in mock.problem_title
        assert "AI_PROVIDER" in mock.problem_description

    def test_gemini_provider_defaults(self):
        """Verify Gemini provider configures correct endpoint and flash lite model."""
        engine = AIEngineService(api_key="test-key", provider="gemini")
        assert engine.model == "gemini-flash-lite-latest"
        assert "generativelanguage.googleapis.com" in engine.base_url
        assert engine.is_configured is True
