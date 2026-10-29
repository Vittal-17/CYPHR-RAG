import os
import logging
import asyncio
import httpx
import math
import time
import random

from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)

class EmbeddingError(Exception): pass
class EmbeddingQuotaError(EmbeddingError): pass
class EmbeddingConfigurationError(EmbeddingError): pass

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "jina").lower()
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "50"))

JINA_SAFE_TPM = int(os.getenv("JINA_SAFE_TPM", "80000"))
JINA_SAFE_RPM = int(os.getenv("JINA_SAFE_RPM", "80"))
JINA_MAX_CONCURRENCY = int(os.getenv("JINA_MAX_CONCURRENCY", "2"))
EMBEDDING_TOKEN_SAFETY_MARGIN = float(os.getenv("EMBEDDING_TOKEN_SAFETY_MARGIN", "0.15"))
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))

if JINA_SAFE_TPM <= 0 or JINA_SAFE_RPM <= 0 or JINA_MAX_CONCURRENCY <= 0 or EMBEDDING_TOKEN_SAFETY_MARGIN < 0 or EMBEDDING_MAX_RETRIES <= 0:
    raise EmbeddingConfigurationError("Invalid quota configuration for Jina.")


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        pass

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass

    async def close(self):
        pass

    def validate_embedding(self, emb: List[float]):
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError("Embedding must be a non-empty list.")
        if len(emb) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(f"Embedding dimension mismatch. Expected {EMBEDDING_DIMENSIONS}, got {len(emb)}")
        if not all(isinstance(x, (int, float)) for x in emb):
            raise EmbeddingError("Embedding must contain numeric values.")

class JinaQuotaGovernor:
    def __init__(self, safe_tpm: int, safe_rpm: int):
        self.safe_tpm = safe_tpm
        self.safe_rpm = safe_rpm
        self.history = []
        self.lock = asyncio.Lock()

    def _clean(self, now: float):
        cutoff = now - 60.0
        self.history = [h for h in self.history if h['time'] > cutoff]

    async def acquire(self, tokens: int):
        if tokens > self.safe_tpm:
            raise EmbeddingQuotaError(f"Request token estimation ({tokens}) exceeds safe TPM ceiling ({self.safe_tpm}).")

        while True:
            wait_time = 0.0
            async with self.lock:
                now = time.time()
                self._clean(now)
                current_tokens = sum(h['tokens'] for h in self.history)
                current_reqs = len(self.history)

                if current_reqs < self.safe_rpm and (current_tokens + tokens) <= self.safe_tpm:
                    self.history.append({'time': now, 'tokens': tokens})
                    return

                if current_reqs >= self.safe_rpm:
                    wait_time = max(0.1, self.history[0]['time'] + 60.0 - now)
                else:
                    needed = (current_tokens + tokens) - self.safe_tpm
                    freed = 0
                    wait_time = 0.1
                    for h in self.history:
                        freed += h['tokens']
                        if freed >= needed:
                            wait_time = max(0.1, h['time'] + 60.0 - now)
                            break

            if wait_time > 0:
                await asyncio.sleep(wait_time)

    async def record_actual(self, estimated: int, actual: int):
        if actual > estimated:
            async with self.lock:
                now = time.time()
                self.history.append({'time': now, 'tokens': actual - estimated})

class JinaEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.api_key = os.getenv("JINA_API_KEY")
        if not self.api_key:
            raise EmbeddingConfigurationError("JINA_API_KEY is missing from environment.")
        self._client = None
        self.provider_id = "jina"
        self.model_id = os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3")
        self.dimensions = EMBEDDING_DIMENSIONS

        self.quota_governor = JinaQuotaGovernor(JINA_SAFE_TPM, JINA_SAFE_RPM)
        self.concurrency_semaphore = asyncio.Semaphore(JINA_MAX_CONCURRENCY)

    def estimate_tokens(self, texts: List[str]) -> int:
        total_chars = sum(len(t) for t in texts)
        base_estimate = total_chars / 4.0
        return int(base_estimate * (1.0 + EMBEDDING_TOKEN_SAFETY_MARGIN))

    @property
    def client(self) -> httpx.AsyncClient:
        # Lazy initialization ensures client binds to the correct running event loop
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client


    async def close(self):
        if self._client is not None:
            if not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _post_with_retry(self, payload: dict, estimated_tokens: int) -> dict:
        url = "https://api.jina.ai/v1/embeddings"
        for attempt in range(EMBEDDING_MAX_RETRIES):
            # Quota gate on every attempt
            await self.quota_governor.acquire(estimated_tokens)

            # Concurrency acquired ONLY during the HTTP request
            try:
                async with self.concurrency_semaphore:
                    resp = await self.client.post(url, headers=self._get_headers(), json=payload)
            except httpx.RequestError as e:
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Network error: {e}. Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                raise EmbeddingError(f"Network failure connecting to Jina API: {str(e)}") from e

            # Semaphore is now safely released

            if resp.status_code in (401, 403):
                raise EmbeddingConfigurationError(f"Jina API authentication failed: {resp.status_code}")
            if resp.status_code in (400, 422):
                raise EmbeddingError(f"Invalid request to Jina API: {resp.status_code} - {resp.text}")
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait_time = int(retry_after)
                else:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    logger.warning(f"Jina 429 Rate Limit. Retrying in {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time) # Safe backoff outside semaphore
                    continue
                raise EmbeddingQuotaError("Embedding provider quota is exhausted.")
            if resp.status_code >= 500:
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(wait_time) # Safe backoff outside semaphore
                    continue
                raise EmbeddingError(f"Jina API server error: {resp.status_code}")

            resp.raise_for_status()
            data = resp.json()

            usage = data.get("usage", {})
            actual_tokens = usage.get("total_tokens")
            if actual_tokens and isinstance(actual_tokens, int):
                # Only add positive differences. This accurately reflects conservative tracking.
                await self.quota_governor.record_actual(estimated_tokens, actual_tokens)

            return data

        raise EmbeddingQuotaError("Jina API failed after max retries.")

    async def embed_query(self, text: str) -> List[float]:
        pass

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass

    async def close(self):
        pass

    def validate_embedding(self, emb: List[float]):
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError("Embedding must be a non-empty list.")
        if len(emb) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(f"Embedding dimension mismatch. Expected {EMBEDDING_DIMENSIONS}, got {len(emb)}")
        if not all(isinstance(x, (int, float)) for x in emb):
            raise EmbeddingError("Embedding must contain numeric values.")

class JinaEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.api_key = os.getenv("JINA_API_KEY")
        if not self.api_key:
            raise EmbeddingConfigurationError("JINA_API_KEY is missing from environment.")
        self._client = None
        self.provider_id = "jina"
        self.model_id = os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3")
        self.dimensions = EMBEDDING_DIMENSIONS

        self.quota_governor = JinaQuotaGovernor(JINA_SAFE_TPM, JINA_SAFE_RPM)
        self.concurrency_semaphore = asyncio.Semaphore(JINA_MAX_CONCURRENCY)

    def estimate_tokens(self, texts: List[str]) -> int:
        total_chars = sum(len(t) for t in texts)
        base_estimate = total_chars / 4.0
        return int(base_estimate * (1.0 + EMBEDDING_TOKEN_SAFETY_MARGIN))

    @property
    def client(self) -> httpx.AsyncClient:
        # Lazy initialization ensures client binds to the correct running event loop
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client


    async def close(self):
        if self._client is not None:
            if not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _post_with_retry(self, payload: dict, estimated_tokens: int) -> dict:
        url = "https://api.jina.ai/v1/embeddings"
        for attempt in range(EMBEDDING_MAX_RETRIES):
            # Quota gate on every attempt
            await self.quota_governor.acquire(estimated_tokens)

            # Concurrency acquired ONLY during the HTTP request
            try:
                async with self.concurrency_semaphore:
                    resp = await self.client.post(url, headers=self._get_headers(), json=payload)
            except httpx.RequestError as e:
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Network error: {e}. Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                raise EmbeddingError(f"Network failure connecting to Jina API: {str(e)}") from e

            # Semaphore is now safely released

            if resp.status_code in (401, 403):
                raise EmbeddingConfigurationError(f"Jina API authentication failed: {resp.status_code}")
            if resp.status_code in (400, 422):
                raise EmbeddingError(f"Invalid request to Jina API: {resp.status_code} - {resp.text}")
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait_time = int(retry_after)
                else:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    logger.warning(f"Jina 429 Rate Limit. Retrying in {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time) # Safe backoff outside semaphore
                    continue
                raise EmbeddingQuotaError("Embedding provider quota is exhausted.")
            if resp.status_code >= 500:
                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(wait_time) # Safe backoff outside semaphore
                    continue
                raise EmbeddingError(f"Jina API server error: {resp.status_code}")

            resp.raise_for_status()
            data = resp.json()

            usage = data.get("usage", {})
            actual_tokens = usage.get("total_tokens")
            if actual_tokens and isinstance(actual_tokens, int):
                # Only add positive differences. This accurately reflects conservative tracking.
                await self.quota_governor.record_actual(estimated_tokens, actual_tokens)

            return data

        raise EmbeddingQuotaError("Jina API failed after max retries.")

    async def embed_query(self, text: str) -> List[float]:
        if not text or not text.strip():
            raise EmbeddingError("Cannot embed empty text.")

        estimated_tokens = self.estimate_tokens([text])
        if estimated_tokens > self.quota_governor.safe_tpm:
            raise EmbeddingQuotaError(f"Query exceeds the safe TPM ceiling ({estimated_tokens} > {self.quota_governor.safe_tpm}).")

        payload = {
            "model": self.model_id,
            "dimensions": EMBEDDING_DIMENSIONS,
            "task": "retrieval.query",
            "input": text
        }

        data = await self._post_with_retry(payload, estimated_tokens)

        embs = data.get("data", [])
        if not embs or len(embs) != 1:
            raise EmbeddingError("Expected exactly one embedding from Jina API.")

        vec = embs[0].get("embedding")
        self.validate_embedding(vec)

        # Verify valid numerics specifically for NaN/Inf
        if not all(math.isfinite(x) for x in vec):
            raise EmbeddingError("Embedding contains invalid numeric values (NaN/Inf).")

        return vec

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        sub_batches = []
        current_batch = []
        current_tokens = 0

        for text in texts:
            est = self.estimate_tokens([text])
            if est > self.quota_governor.safe_tpm:
                raise EmbeddingQuotaError(f"A single document chunk exceeds the safe TPM ceiling ({est} > {self.quota_governor.safe_tpm}).")

            if current_tokens + est > self.quota_governor.safe_tpm or len(current_batch) >= EMBEDDING_BATCH_SIZE:
                sub_batches.append(current_batch)
                current_batch = [text]
                current_tokens = est
            else:
                current_batch.append(text)
                current_tokens += est

        if current_batch:
            sub_batches.append(current_batch)

        result = [None] * len(texts)
        global_idx_offset = 0

        for batch in sub_batches:
            estimated_tokens = self.estimate_tokens(batch)
            payload = {
                "model": self.model_id,
                "dimensions": EMBEDDING_DIMENSIONS,
                "task": "retrieval.passage",
                "input": batch
            }

            data = await self._post_with_retry(payload, estimated_tokens)

            embs = data.get("data", [])
            if len(embs) != len(batch):
                raise EmbeddingError(f"Batch response count mismatch. Expected {len(batch)}, got {len(embs)}")

            for item in embs:
                idx = item.get("index")
                if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(batch):
                    raise EmbeddingError(f"Invalid or out-of-bounds response index from Jina API: {idx}")

                global_idx = global_idx_offset + idx
                if result[global_idx] is not None:
                    raise EmbeddingError(f"Duplicate response index from Jina API: {idx}")

                vec = item.get("embedding")
                self.validate_embedding(vec)
                if not all(math.isfinite(x) for x in vec):
                    raise EmbeddingError("Embedding contains invalid numeric values (NaN/Inf).")

                result[global_idx] = vec

            global_idx_offset += len(batch)

        if any(v is None for v in result):
            raise EmbeddingError("Missing embeddings in batch response.")

        return result

_provider_instance = None

def get_embedding_provider() -> EmbeddingProvider:
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    if EMBEDDING_PROVIDER == "jina":
        _provider_instance = JinaEmbeddingProvider()
    elif EMBEDDING_PROVIDER == "google":
        raise EmbeddingConfigurationError("Google embedding provider is deprecated and removed. Please use 'jina'.")
    else:
        raise EmbeddingConfigurationError(f"Unknown EMBEDDING_PROVIDER: {EMBEDDING_PROVIDER}")

    return _provider_instance




async def close_embedding_provider():
    global _provider_instance
    if _provider_instance is not None:
        await _provider_instance.close()
        _provider_instance = None
