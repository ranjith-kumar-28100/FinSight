"""Chat Agent — conversational Q&A grounded on the user's processed data.

Uses LangChain's tool-calling interface with AzureChatOpenAI.
Tools are Python functions that run parameterized SQL queries or hit the
in-memory RAG index — the LLM translates the user question into tool calls;
code fetches the data; the LLM formats the final answer.

The LLM NEVER computes money totals — it only orchestrates queries and
formats answers.
"""

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI

from backend.config import AzureOpenAIConfig
from backend.db.repository import TransactionRepository
from backend.llm.provider import LLMProvider
from backend.models.transaction import TransactionSource
from backend.rag.store import TransactionRAGStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are FinSight, a personal finance assistant grounded strictly on the
user's own transaction data. You have access to tools that query their database
and a hybrid retrieval index over their transactions.

Data model:
- The HDFC bank statement is the ONLY source of truth for amounts, dates,
  income, spend, and totals. Every aggregate tool already filters to bank rows.
- GPay and Paytm records exist only as enrichment — they explain what cryptic
  UPI narrations on the bank side actually went to. Use `get_wallet_detail`
  only when the user explicitly asks "where did this UPI go" / "what was paid
  to whom" for a specific bank transaction.

Tool selection:
- HARD numbers (totals, monthly summaries, category totals, top merchants,
  goal status, recurring series) → use the SQL tools
  (`get_category_total`, `get_monthly_summary`, `list_categories_summary`,
   `get_all_monthly_maps`, `get_recurring_series`, `get_goal_status`).
- SEMANTIC / EXPLORATORY questions ("transactions related to travel",
  "what did I order from Big Basket last month", "show me anything cafe-like")
  → use `search_transactions` first to retrieve relevant rows, then summarise.
- Combine when useful: search for relevant transactions, then call an aggregation
  tool on the surfaced category/date range to produce exact totals.

Rules:
- Always use tools to fetch numbers. NEVER invent or estimate money figures.
- When the tool returns data, use those exact numbers in your answer.
- Keep answers concise. Show supporting data (top transactions, monthly breakdown) when helpful.
- All amounts are in Indian Rupees (₹).
- If a tool returns empty data, say so clearly instead of guessing.
"""


def _build_rag(
    config: AzureOpenAIConfig,
    repo: TransactionRepository,
) -> Optional[TransactionRAGStore]:
    """Build the hybrid retrieval index over bank rows + orphan wallet rows.

    Orphan wallet rows are included (tagged `source='gpay'|'paytm'`) so the
    LLM can drill into them when the user asks about a wallet-only payment.
    They are NEVER summed — totals tools already filter to bank rows.
    """
    try:
        store = TransactionRAGStore(LLMProvider(config))
        bank_rows = repo.get_transactions(bank_only=True)
        orphan_wallet = repo.get_orphan_wallet_transactions()
        store.index_all(bank_rows + orphan_wallet)
        logger.info(
            "Chat RAG index ready: %d points (dense=%s).",
            store.size, store.dense_enabled,
        )
        return store
    except Exception as e:
        logger.warning(
            "RAG index build failed (%s) — chat will run without search_transactions.", e)
        return None


def _make_tools(repo: TransactionRepository, rag: Optional[TransactionRAGStore]):
    """Create LangChain tools bound to the given repository and RAG store."""

    @tool
    def query_transactions(
        category: str = "",
        direction: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 10,
    ) -> str:
        """Fetch BANK transactions filtered by category, direction (debit/credit),
        and/or date range (YYYY-MM-DD). Returns top `limit` transactions as JSON.

        Wallet (GPay/Paytm) rows are excluded — for those use get_wallet_detail."""
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else None
        txns = repo.get_transactions(
            start_date=start,
            end_date=end,
            category=category or None,
            direction=direction or None,
            bank_only=True,
        )[:limit]
        rows = [
            {
                "txn_id": t.txn_id,
                "date": str(t.date),
                "amount": str(t.amount),
                "direction": t.direction.value,
                "merchant": t.enriched_counterparty or t.counterparty,
                "category": t.category,
                "description": t.raw_description[:60],
            }
            for t in txns
        ]
        return json.dumps(rows)

    @tool
    def get_monthly_summary(month: str) -> str:
        """Get the money map for a given month (YYYY-MM format):
        income, total_spend, fixed_obligations, discretionary, net_savings, savings_rate."""
        maps = repo.get_monthly_maps()
        for m in maps:
            if m["month"] == month:
                return json.dumps({k: str(v) for k, v in m.items()})
        return json.dumps({"error": f"No data for month {month}"})

    @tool
    def get_category_total(
        category: str,
        start_date: str = "",
        end_date: str = "",
    ) -> str:
        """Get total spend and transaction count for one category in a date range."""
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else None
        result = repo.get_category_total(category, start, end)
        return json.dumps(result)

    @tool
    def list_categories_summary(start_date: str = "", end_date: str = "") -> str:
        """List all spending categories with total spend and transaction count
        for a date range (YYYY-MM-DD). Useful for 'where did my money go' questions."""
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else None
        data = repo.get_categories_summary(start, end)
        return json.dumps(data)

    @tool
    def get_recurring_series() -> str:
        """Return all detected recurring payments (EMIs, SIPs, subscriptions, etc.)."""
        series = repo.get_recurring_series()
        return json.dumps(series)

    @tool
    def get_all_monthly_maps() -> str:
        """Return income, spend, savings for each month — useful for trend questions."""
        maps = repo.get_monthly_maps()
        return json.dumps([{k: str(v) for k, v in m.items()} for m in maps])

    @tool
    def get_goal_status() -> str:
        """Return the latest saved goal verdict, gap, and suggestions."""
        goal = repo.get_latest_goal()
        if not goal:
            return json.dumps({"status": "No goal set yet."})
        return json.dumps({
            "description": goal["description"],
            "target_amount": str(goal["target_amount"]),
            "horizon_months": goal["horizon_months"],
            "verdict": goal["verdict"],
            "gap_per_month": str(goal["gap_per_month"]),
            "suggestions": goal["suggestions"],
        })

    @tool
    def search_transactions(
        query: str,
        k: int = 8,
        source: str = "",
        direction: str = "",
        category: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> str:
        """Hybrid-search the transaction index (dense semantic + BM25 sparse,
        fused via RRF) for transactions matching a natural-language query.

        Use for fuzzy/exploratory questions where the user names a merchant,
        topic, or theme rather than an exact category. Optional filters narrow
        the candidate pool: source ('bank'|'gpay'|'paytm'), direction
        ('debit'|'credit'), category (taxonomy name), start_date / end_date
        (YYYY-MM-DD, inclusive).

        Returns top-k matches as JSON, each with merchant, date, amount,
        category, and the raw description so the LLM can decide what to do
        next (e.g. follow up with `get_category_total` for hard numbers)."""
        if rag is None or rag.size == 0:
            return json.dumps({"info": "Search index is empty — try after the pipeline has run."})
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else None
        hits = rag.hybrid_search(
            query,
            k=max(1, min(int(k), 25)),
            source=source or None,
            direction=direction or None,
            category=category or None,
            start_date=start,
            end_date=end,
        )
        return json.dumps([h.to_dict() for h in hits])

    @tool
    def get_wallet_detail(bank_txn_id: str) -> str:
        """Show the GPay/Paytm row(s) linked to a specific bank transaction.

        Use ONLY when the user asks where a particular UPI debit on the bank
        statement went (i.e. needs the cleaner merchant name from the wallet)."""
        rows = repo.get_wallet_detail_for_bank(bank_txn_id)
        if not rows:
            return json.dumps({"info": "No wallet record linked to this bank transaction."})
        return json.dumps([
            {
                "date": str(r.date),
                "source": r.source.value,
                "amount": str(r.amount),
                "counterparty": r.counterparty,
                "description": r.raw_description[:120],
                "upi_ref": r.source_ref,
            }
            for r in rows
        ])

    return [
        query_transactions,
        get_monthly_summary,
        get_category_total,
        list_categories_summary,
        get_recurring_series,
        get_all_monthly_maps,
        get_goal_status,
        search_transactions,
        get_wallet_detail,
    ]


class ChatAgent:
    """Stateful chat agent. Holds conversation history for the session."""

    def __init__(
        self,
        config: AzureOpenAIConfig,
        repo: TransactionRepository,
        rag: Optional[TransactionRAGStore] = None,
    ) -> None:
        self._repo = repo
        self._rag = rag if rag is not None else _build_rag(config, repo)
        self._tools = _make_tools(repo, self._rag)
        self._tool_map = {t.name: t for t in self._tools}

        self._llm = AzureChatOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
            azure_deployment=config.deployment_reasoning,
            temperature=0.2,
            max_tokens=1000,
        ).bind_tools(self._tools)

        self._history: list = [SystemMessage(content=SYSTEM_PROMPT)]

    def chat(
        self,
        user_message: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """Process a user message and return the assistant's response.

        When ``start_date`` / ``end_date`` are provided, the LLM is told that
        every aggregation and search should default to that window unless the
        user explicitly overrides it.
        """
        if start_date or end_date:
            window = (
                f"ACTIVE DATE FILTER: "
                f"{start_date.isoformat() if start_date else 'beginning'} "
                f"to {end_date.isoformat() if end_date else 'end'}. "
                "Apply this range to every tool call (start_date/end_date) "
                "unless the user explicitly mentions a different period."
            )
            self._history.append(SystemMessage(content=window))

        self._history.append(HumanMessage(content=user_message))

        # LLM responds (may include tool_calls)
        response: AIMessage = self._llm.invoke(self._history)
        self._history.append(response)

        # Execute any tool calls
        if response.tool_calls:
            for tc in response.tool_calls:
                tool_fn = self._tool_map.get(tc["name"])
                if tool_fn is None:
                    result = json.dumps(
                        {"error": f"Unknown tool: {tc['name']}"})
                else:
                    try:
                        result = tool_fn.invoke(tc["args"])
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                self._history.append(ToolMessage(
                    content=str(result), tool_call_id=tc["id"]))

            # Get final answer with tool results injected
            final: AIMessage = self._llm.invoke(self._history)
            self._history.append(final)
            return final.content or ""

        return response.content or ""

    def reset(self) -> None:
        """Clear conversation history (keep system prompt)."""
        self._history = [SystemMessage(content=SYSTEM_PROMPT)]
