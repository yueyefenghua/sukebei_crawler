from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx


BLOCK_STATUS = {403, 429, 503}


class BlockedStatus(RuntimeError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"Blocked or rate-limited status {status}: {url}")
        self.status = status
        self.url = url


@dataclass
class HttpResponse:
    url: str
    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        accept_language: str,
        timeout_seconds: int,
        retry_count: int,
        block_status: set[int] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.block_status = block_status or BLOCK_STATUS
        self.base_headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br",
        }
        self.client = httpx.Client(
            headers=self.base_headers,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            trust_env=False,
        )

    def get(self, url: str, *, referer: str | None = None) -> HttpResponse:
        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                headers = {}
                if referer:
                    headers["Referer"] = referer
                response = self.client.get(url, headers=headers)
                if response.status_code in self.block_status:
                    raise BlockedStatus(response.status_code, url)
                response.raise_for_status()
                return HttpResponse(
                    url=str(response.url),
                    status=response.status_code,
                    body=response.content,
                    headers=dict(response.headers),
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = exc

            if attempt < self.retry_count:
                time.sleep(10 if attempt == 0 else 30)

        assert last_error is not None
        raise last_error

    def close(self) -> None:
        self.client.close()


def polite_sleep(delay_seconds: float, jitter_seconds: float) -> None:
    sleep_for = delay_seconds + (random.uniform(0, jitter_seconds) if jitter_seconds > 0 else 0)
    time.sleep(sleep_for)
