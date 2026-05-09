"""Fakes for the Fetcher protocol and tier-classifier protocol.

`FakeFetcher` maps URLs → FetchResult-like canned responses.
`FakeTierClassifier` maps URLs → (tier, rationale, confidence, peer_reviewed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deep_research_agent.retrieval.fetch import FetchResult
from deep_research_agent.schemas.enums import Tier


@dataclass
class FakeFetcher:
    _responses: dict[str, FetchResult | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def script(self, url: str, result: FetchResult | None) -> None:
        self._responses[url] = result

    async def fetch(self, url: str) -> FetchResult | None:
        self.calls.append(url)
        if url not in self._responses:
            raise KeyError(
                f"FakeFetcher: no scripted response for {url!r}. "
                f"Registered: {list(self._responses)}"
            )
        return self._responses[url]


@dataclass
class FakeTierClassifier:
    _responses: dict[str, tuple[Tier, str, float, bool]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def script(
        self, url: str, *, tier: Tier, rationale: str, confidence: float, peer_reviewed: bool
    ) -> None:
        self._responses[url] = (tier, rationale, confidence, peer_reviewed)

    async def classify(
        self, *, title: str, url: str, snippet: str, content: str
    ) -> tuple[Tier, str, float, bool]:
        # Intentionally unused: the fake keys on `url` only so tests control the mapping.
        del title, snippet, content
        self.calls.append(url)
        if url not in self._responses:
            raise KeyError(
                f"FakeTierClassifier: no scripted response for {url!r}. "
                f"Registered: {list(self._responses)}"
            )
        return self._responses[url]
