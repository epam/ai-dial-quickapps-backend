import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional, Set

from tests.test_runner.cache.cache_request import CacheRequest
from tests.test_runner.cache.cache_response import CacheResponse
from tests.test_runner.similarity_checker import get_similarity

logger = logging.getLogger("__name__")


def get_cache_key(data: CacheRequest):
    """Generate a hash key for the input string."""
    return hashlib.md5(str(data).encode()).hexdigest()


SIMILARITY_THRESHOLD = 0.7


class LlmCache:

    def __init__(self, cache_path: Path, enable_cache=True):
        self.cache_path = Path(cache_path)
        self.enable_cache = enable_cache
        self.cache_responses: List[CacheResponse] = []
        self.used_cache_responses: set = set()

        if self.enable_cache:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            self._load_cache()

    def _load_cache(self):
        """Scans the cache_path folder and loads all *.response files."""
        path = self.cache_path

        for file_path in path.glob("*.response"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cache_response = CacheResponse(
                        status_code=data["response"]["status_code"],
                        headers=data["response"]["headers"],
                        body=data["body"],
                        body_encoded=data["body_encoded"],
                        request=CacheRequest(**data["request"]),
                    )
                    self.cache_responses.append(cache_response)
            except (json.JSONDecodeError, FileNotFoundError, TypeError) as e:
                logger.error(f"Error loading cache file {file_path}: {e}")

    def get_cache_response(self, request: CacheRequest) -> Optional[CacheResponse]:
        """
        Iterates through all CacheResponses and checks if it matches with the given CacheRequest object.
        Returns the top-scoring CacheResponse and its score.
        """
        top_score = -1.0
        top_response: Optional[CacheResponse] = None

        for cached_response in self.cache_responses:
            score = self._compare_requests(request, cached_response.request)
            if score > top_score:
                top_score = score
                top_response = cached_response

        return top_response

    def _compare_requests(self, request: CacheRequest, cached_request: CacheRequest) -> float:
        """Compares the incoming request with a cached request and returns a score (or False if no match)."""

        # Exact match checks
        if request.system_message != cached_request.system_message:
            logger.debug(
                f"System message not match: {request.system_message} != {cached_request.system_message}"
            )
            return -1.0
        if request.model != cached_request.model:
            logger.debug(f"Model not match: {request.model} != {cached_request.model}")
            return -1.0
        if request.temperature != cached_request.temperature:
            logger.debug(
                f"Temperature not match: {request.temperature} != {cached_request.temperature}"
            )
            return -1.0

        # Similarity checks for user messages
        user_similarity_score = self._calculate_average_similarity(
            request.user_message, cached_request.user_message
        )
        if user_similarity_score < SIMILARITY_THRESHOLD:
            logger.debug(f"User message score {user_similarity_score} below threshold")
            return -1.0

        # Similarity checks for assistant messages
        assistant_similarity_score = self._calculate_average_similarity(
            request.assistant_message, cached_request.assistant_message
        )
        if assistant_similarity_score < SIMILARITY_THRESHOLD:
            logger.debug(f"Assistant message score {assistant_similarity_score} below threshold")
            return -1.0

        # If all checks pass, return the overall score (average of user and assistant scores)
        overall_score = (user_similarity_score + assistant_similarity_score) / 2
        logger.debug(f"Overall score: {overall_score}")
        return overall_score

    def _calculate_average_similarity(self, list1: List[str], list2: List[str]) -> float:
        """Calculates the average similarity score between two lists of strings."""
        if not list1 or not list2:
            # If either list is empty, consider it a perfect match (or handle differently as needed)
            return 1.0 if not list1 and not list2 else 0.0

        total_similarity = 0.0
        min_len = min(len(list1), len(list2))

        for i in range(min_len):
            similarity = get_similarity(list1[i], list2[i])
            total_similarity += similarity

        return total_similarity / min_len

    def store(self, data: CacheResponse):
        if not self.enable_cache:
            return

        file_path = self.get_cache_path(data)
        if isinstance(data, CacheResponse):
            with file_path.open('w') as file:
                file.write(data.serialize())

        logger.debug("Response cached in file " + str(file_path))

    def get_cache_path(self, data):
        cache_key = get_cache_key(data.request)
        file_path = self.cache_path / f"{cache_key}.response"
        return file_path

    def cleanup(self, to_delete: Set[CacheResponse]):
        file_path = ""
        for response in to_delete:
            try:
                file_path = self.get_cache_path(response)
                file_path.unlink()
                logger.info(f"Deleted: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting {file_path}: {e}")
