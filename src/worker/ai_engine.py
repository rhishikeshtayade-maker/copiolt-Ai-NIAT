"""OpenAI API integration for coding analysis and vision explanations."""

import os
from typing import Optional
from src.common.config import settings
from src.common.logger import get_logger
from src.common.schemas import AIAnalysisRequest, AIAnalysisResponse, current_utc_time

logger = get_logger("Worker.AIEngine")


class AIEngineService:
    """Provides coding guidance and visual question explanation via OpenAI API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or settings.openai_model
        self._client = None

        if self.api_key:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=self.api_key)
                logger.info(f"OpenAI service initialized with model '{self.model}'.")
            except Exception as e:
                logger.warning(f"Could not initialize OpenAI client: {e}")
        else:
            logger.info("OPENAI_API_KEY not configured. AI engine will operate in local mock/guidance mode.")

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
            try:
                messages = [{"role": "system", "content": system_prompt}]
                user_content = [{"type": "text", "text": request.prompt}]

                if request.image_base64:
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{request.image_base64}"
                            },
                        }
                    )

                messages.append({"role": "user", "content": user_content})

                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=1500,
                )

                content = response.choices[0].message.content or "No response generated."
                return AIAnalysisResponse(
                    worker_id=request.worker_id,
                    explanation=content,
                    requires_student_review=True,
                    auto_submission_permitted=False,
                    analyzed_at=current_utc_time(),
                )
            except Exception as e:
                logger.error(f"Error querying OpenAI API: {e}")
                raise RuntimeError(f"AI reasoning failure: {str(e)}")

        # Fallback local guidance when API key is not yet set
        return AIAnalysisResponse(
            worker_id=request.worker_id,
            explanation=(
                f"[Local Simulation Engine]: Analysis for question '{request.prompt}'. "
                "To connect live GPT-4o vision analysis, provide OPENAI_API_KEY in your .env file."
            ),
            suggested_code="# Suggested template:\ndef solve_problem():\n    pass\n",
            requires_student_review=True,
            auto_submission_permitted=False,
            analyzed_at=current_utc_time(),
        )
