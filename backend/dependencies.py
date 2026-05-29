"""Shared dependency-injected singletons (config, repo, chat agent).

We hold a small in-memory cache so each request reuses the same DB connection
factory and RAG store. The cache invalidates when the upload pipeline finishes
so freshly ingested data is picked up immediately."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from backend.agents.chat import ChatAgent
from backend.config import AppConfig, get_config
from backend.db.repository import TransactionRepository
from backend.db.schema import init_db

logger = logging.getLogger(__name__)


class _State:
    """Process-local singletons. Initialised lazily on first request."""

    def __init__(self) -> None:
        # RLock so methods can call each other while holding the lock.
        self._lock = threading.RLock()
        self._config: AppConfig | None = None
        self._repo: TransactionRepository | None = None
        self._chat_agent: ChatAgent | None = None

    def config(self) -> AppConfig:
        with self._lock:
            if self._config is None:
                self._config = get_config()
                init_db(self._config.db_path)
            return self._config

    def repo(self) -> TransactionRepository:
        with self._lock:
            if self._repo is None:
                cfg = self.config()
                self._repo = TransactionRepository(cfg.db_path)
            return self._repo

    def chat_agent(self) -> ChatAgent:
        # Cached agent — rebuilt on `invalidate_chat()`
        with self._lock:
            if self._chat_agent is None:
                cfg = self.config()
                self._chat_agent = ChatAgent(cfg.azure, self.repo())
            return self._chat_agent

    def invalidate_chat(self) -> None:
        """Drop the cached chat agent so the next chat call rebuilds the RAG index."""
        with self._lock:
            self._chat_agent = None
            logger.info("Chat agent cache invalidated.")


_STATE = _State()


def get_app_config() -> AppConfig:
    return _STATE.config()


def get_repo() -> TransactionRepository:
    return _STATE.repo()


def get_chat_agent() -> ChatAgent:
    return _STATE.chat_agent()


def invalidate_chat_cache() -> None:
    _STATE.invalidate_chat()
