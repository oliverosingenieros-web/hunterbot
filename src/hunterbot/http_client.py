"""Cliente HTTP compartido con rate limiting, reintentos y headers realistas."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Pool de User-Agents reales de navegadores modernos (2025-2026)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 OPR/112.0.0.0",
]

_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class HunterHTTPClient:
    """Cliente HTTP con rate limiting por dominio, reintentos y headers realistas."""

    def __init__(
        self,
        rate_limit_default: float = 2.0,
        max_retries: int = 3,
        timeout_connect: float = 15.0,
        timeout_read: float = 30.0,
        respect_robots: bool = True,
    ) -> None:
        self._rate_limit_default = rate_limit_default
        self._max_retries = max_retries
        self._respect_robots = respect_robots
        self._last_request: dict[str, float] = {}
        self._robots_cache: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=timeout_connect,
                read=timeout_read,
                write=10.0,
                pool=10.0,
            ),
            follow_redirects=True,
            http2=False,
        )

    async def close(self) -> None:
        """Cierra el cliente HTTP."""
        await self._client.aclose()

    async def __aenter__(self) -> HunterHTTPClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _get_domain(self, url: str) -> str:
        """Extrae el dominio de una URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.hostname or ""

    def _random_ua(self) -> str:
        """Devuelve un User-Agent aleatorio."""
        return random.choice(_USER_AGENTS)

    async def _enforce_rate_limit(self, domain: str, rate_limit: float) -> None:
        """Espera si es necesario para respetar el rate limit por dominio."""
        async with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            if elapsed < rate_limit:
                wait = rate_limit - elapsed + random.uniform(0.1, 0.5)
                logger.debug("Rate limit: esperando %.1fs para %s", wait, domain)
                await asyncio.sleep(wait)
            self._last_request[domain] = time.monotonic()

    async def get(
        self,
        url: str,
        *,
        rate_limit: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        max_retries: int | None = None,
    ) -> httpx.Response:
        """GET request con rate limiting, reintentos y headers realistas."""
        domain = self._get_domain(url)
        rl = rate_limit if rate_limit is not None else self._rate_limit_default
        retries = max_retries if max_retries is not None else self._max_retries

        merged_headers = {**_DEFAULT_HEADERS, "User-Agent": self._random_ua()}
        if headers:
            merged_headers.update(headers)

        for attempt in range(retries):
            await self._enforce_rate_limit(domain, rl)
            try:
                response = await self._client.get(
                    url, headers=merged_headers, params=params
                )

                if response.status_code == 429:
                    wait = (2**attempt) + random.uniform(1, 3)
                    logger.warning(
                        "429 Too Many Requests de %s, esperando %.1fs (intento %d/%d)",
                        domain,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = (2**attempt) + random.uniform(0.5, 1.5)
                    logger.warning(
                        "Error %d de %s, reintentando en %.1fs (intento %d/%d)",
                        response.status_code,
                        domain,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    await asyncio.sleep(wait)
                    continue

                return response

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                wait = (2**attempt) + random.uniform(0.5, 1.5)
                logger.warning(
                    "Error de conexión con %s: %s. Reintentando en %.1fs (intento %d/%d)",
                    domain,
                    str(e),
                    wait,
                    attempt + 1,
                    retries,
                )
                if attempt < retries - 1:
                    await asyncio.sleep(wait)
                else:
                    raise

        # Si llegamos aquí, todos los intentos fallaron
        raise httpx.HTTPError(
            f"Todos los reintentos agotados para {url}"
        )

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
        rate_limit: float | None = None,
    ) -> httpx.Response:
        """POST request con rate limiting."""
        domain = self._get_domain(url)
        rl = rate_limit if rate_limit is not None else self._rate_limit_default

        merged_headers = {**_DEFAULT_HEADERS, "User-Agent": self._random_ua()}
        if headers:
            merged_headers.update(headers)

        await self._enforce_rate_limit(domain, rl)

        return await self._client.post(
            url, data=data, json=json, headers=merged_headers
        )

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        rate_limit: float | None = None,
    ) -> dict:
        """GET que parsea JSON directamente."""
        api_headers = {
            "Accept": "application/json",
            "User-Agent": self._random_ua(),
        }
        if headers:
            api_headers.update(headers)

        response = await self.get(
            url, headers=api_headers, params=params, rate_limit=rate_limit
        )
        response.raise_for_status()
        return response.json()
