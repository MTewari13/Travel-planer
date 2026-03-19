"""Cohere AI service for agent reasoning and embeddings."""

import json
import os
import re
import asyncio
import logging
from typing import Any, Optional

import cohere
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("cohere_service")


class CohereService:
    """Wrapper around Cohere API for text generation and embeddings."""

    def __init__(self):
        api_key = os.getenv("COHERE_API_KEY", "")
        if not api_key or api_key == "your-cohere-api-key-here":
            logger.warning(
                "⚠️  COHERE_API_KEY not set. LLM features will use fallback logic."
            )
            self._client = None
        else:
            self._client = cohere.ClientV2(api_key)
            logger.info("✅ Cohere client initialized")

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful travel planning assistant.",
        model: str = "command-a-03-2025",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Generate text using Cohere chat API."""
        if not self._client:
            return ""

        try:
            response = await asyncio.to_thread(
                self._client.chat,
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.message.content[0].text
        except Exception as e:
            logger.error(f"Cohere generation error: {e}")
            return ""

    async def embed(
        self,
        texts: list[str],
        model: str = "embed-v4.0",
        input_type: str = "search_document",
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not self._client:
            return []

        try:
            response = await asyncio.to_thread(
                self._client.embed,
                texts=texts,
                model=model,
                input_type=input_type,
                embedding_types=["float"],
            )
            return response.embeddings.float_
        except Exception as e:
            logger.error(f"Cohere embedding error: {e}")
            return []

    async def rank_options(
        self,
        query: str,
        options: list[str],
        model: str = "rerank-v3.5",
    ) -> list[dict]:
        """Rerank options based on relevance to the query."""
        if not self._client:
            return [{"index": i, "relevance_score": 1.0 / (i + 1)} for i in range(len(options))]

        try:
            response = await asyncio.to_thread(
                self._client.rerank,
                model=model,
                query=query,
                documents=options,
                top_n=len(options),
            )
            return [
                {"index": r.index, "relevance_score": r.relevance_score}
                for r in response.results
            ]
        except Exception as e:
            logger.error(f"Cohere rerank error: {e}")
            return [{"index": i, "relevance_score": 1.0 / (i + 1)} for i in range(len(options))]

    async def generate_json(
        self,
        prompt: str,
        fallback: Any = None,
        model: str = "command-a-03-2025",
        max_tokens: int = 2048,
        temperature: float = 0.6,
    ) -> Any:
        """Generate structured JSON data using Cohere. Returns parsed Python object."""
        system_prompt = (
            "You are a travel data API. You MUST respond with ONLY valid JSON. "
            "No markdown, no code fences, no explanations, no text before or after. "
            "Just raw JSON."
        )

        raw = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if not raw:
            logger.warning("Cohere returned empty response for JSON generation")
            return fallback

        # Try to parse directly
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Retry once with explicit correction
        logger.warning("First JSON parse failed, retrying with correction prompt")
        retry_raw = await self.generate(
            prompt=f"Convert this into valid JSON only. No other text:\n\n{raw}",
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        if retry_raw:
            try:
                return json.loads(retry_raw)
            except json.JSONDecodeError:
                fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", retry_raw, re.DOTALL)
                if fence_match:
                    try:
                        return json.loads(fence_match.group(1).strip())
                    except json.JSONDecodeError:
                        pass

        logger.error(f"Failed to parse JSON from Cohere after retry")
        return fallback


# Singleton instance
cohere_service = CohereService()
