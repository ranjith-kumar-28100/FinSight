"""LLM provider abstraction layer.

Thin wrapper over Azure AI Foundry (OpenAI-compatible API).
Designed so you can swap GPT ↔ Claude without touching the rest of the code.

The LLM NEVER computes money totals — it only classifies, explains, and plans.
"""

import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from openai import AzureOpenAI

from backend.config import AzureOpenAIConfig
from backend.taxonomy import CATEGORIES

logger = logging.getLogger(__name__)


@dataclass
class CategorisationResult:
    """Result of LLM-based categorisation."""

    category: str
    subcategory: Optional[str]
    confidence: float
    rationale: str


class LLMProvider:
    """Azure AI Foundry LLM provider for categorisation.

    Uses the OpenAI SDK with Azure endpoint configuration.
    Provider abstraction makes it trivial to swap to Claude/Bedrock later.
    """

    def __init__(self, config: AzureOpenAIConfig) -> None:
        self._config = config
        self._client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
        self._deployment = config.deployment_categorisation
        self._embedding_deployment = config.deployment_embedding

    def embed_batch(self, texts: list[str], batch_size: int = 128) -> list[list[float]]:
        """Embed a batch of texts using the Azure text-embedding deployment.

        Returns one float vector per input text. Falls back to an empty list
        per text if the deployment isn't configured.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start: start + batch_size]
            response = self._client.embeddings.create(
                model=self._embedding_deployment,
                input=chunk,
            )
            vectors.extend(d.embedding for d in response.data)
        return vectors

    def categorise(
        self,
        description: str,
        amount: Decimal,
        direction: str,
    ) -> CategorisationResult:
        """Categorise a single transaction using the LLM.

        The LLM classifies and explains — it NEVER computes money totals.
        """
        category_list = "\n".join(
            f"- {cat}: {', '.join(subs)}" for cat, subs in CATEGORIES.items()
        )

        system_prompt = (
            "You are a personal finance categorisation assistant for Indian transactions. "
            "Given a transaction description, amount, and direction (debit/credit), "
            "classify it into the most appropriate category and subcategory.\n\n"
            "Available categories and subcategories:\n"
            f"{category_list}\n\n"
            "IMPORTANT: You MUST respond with valid JSON only. No other text.\n"
            "Response format:\n"
            '{"category": "...", "subcategory": "...", "confidence": 0.0-1.0, "rationale": "..."}\n\n'
            "Rules:\n"
            "- confidence should reflect how certain you are (0.0 to 1.0)\n"
            "- rationale should briefly explain your reasoning\n"
            "- If unsure, use category 'Other' with low confidence\n"
            "- NEVER compute or verify monetary amounts — only classify"
        )

        user_prompt = (
            f"Transaction: {description}\n"
            f"Amount: ₹{amount}\n"
            f"Direction: {direction}"
        )

        return self._call_llm(system_prompt, user_prompt)

    def categorise_batch(
        self,
        transactions: list[dict],
    ) -> list[CategorisationResult]:
        """Categorise multiple transactions.

        Sends transactions one by one with retry logic.
        Batch API could be used for higher throughput in future.
        """
        results = []
        for txn in transactions:
            try:
                result = self.categorise(
                    description=txn["description"],
                    amount=Decimal(str(txn["amount"])),
                    direction=txn["direction"],
                )
                results.append(result)
            except Exception:
                logger.exception("LLM categorisation failed for transaction")
                results.append(CategorisationResult(
                    category="Other",
                    subcategory=None,
                    confidence=0.0,
                    rationale="LLM categorisation failed — defaulting to Other.",
                ))
        return results

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
    ) -> CategorisationResult:
        """Call the LLM with retry logic and exponential backoff."""
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=256,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from LLM")

                data = json.loads(content)

                return CategorisationResult(
                    category=data.get("category", "Other"),
                    subcategory=data.get("subcategory"),
                    confidence=min(
                        max(float(data.get("confidence", 0.5)), 0.0), 1.0),
                    rationale=data.get("rationale", ""),
                )

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM call attempt %d failed, retrying in %ds...",
                        attempt + 1,
                        wait,
                    )
                    time.sleep(wait)

        logger.error("LLM call failed after %d retries.", max_retries)
        return CategorisationResult(
            category="Other",
            subcategory=None,
            confidence=0.0,
            rationale=f"LLM categorisation failed: {type(last_error).__name__}",
        )
