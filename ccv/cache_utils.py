"""
Cache utilities for CUPCAKE Vanilla application using Redis.
"""

import hashlib
from typing import Any, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils.encoding import force_str


def get_cache_key(*args: Any, prefix: str = "") -> str:
    """
    Generate a cache key from arguments.

    Args:
        *args: Arguments to create key from
        prefix: Optional prefix for the key

    Returns:
        str: Generated cache key
    """
    key_parts = [force_str(arg) for arg in args if arg is not None]
    key_string = ":".join(key_parts)

    if prefix:
        key_string = f"{prefix}:{key_string}"

    # Hash long keys to avoid Redis key length limits
    if len(key_string) > 200:
        key_string = hashlib.md5(key_string.encode()).hexdigest()

    return key_string


def cache_get(key: str) -> Optional[Any]:
    """
    Get value from cache.

    Args:
        key: Cache key

    Returns:
        Cached value or None if not found
    """
    try:
        return cache.get(key)
    except Exception as e:
        # Log error in production
        print(f"Cache get error for key '{key}': {e}")
        return None


def cache_set(key: str, value: Any, timeout: Optional[int] = None) -> bool:
    """
    Set value in cache.

    Args:
        key: Cache key
        value: Value to cache
        timeout: Timeout in seconds (uses CACHE_TTL if not provided)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if timeout is None:
            timeout = getattr(settings, "CACHE_TTL", 900)  # 15 minutes default

        cache.set(key, value, timeout)
        return True
    except Exception as e:
        # Log error in production
        print(f"Cache set error for key '{key}': {e}")
        return False


def cache_delete(key: str) -> bool:
    """
    Delete value from cache.

    Args:
        key: Cache key to delete

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        cache.delete(key)
        return True
    except Exception as e:
        # Log error in production
        print(f"Cache delete error for key '{key}': {e}")
        return False


def cache_delete_pattern(pattern: str) -> bool:
    """
    Delete cache keys matching pattern.

    Args:
        pattern: Pattern to match (e.g., "user:*", "template:123:*")

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        cache.delete_many(cache.keys(pattern))
        return True
    except Exception as e:
        # Log error in production
        print(f"Cache delete pattern error for pattern '{pattern}': {e}")
        return False


def cache_get_or_set(key: str, default_callable, timeout: Optional[int] = None) -> Any:
    """
    Get value from cache or set it using default_callable if not found.

    Args:
        key: Cache key
        default_callable: Function to call to get default value
        timeout: Timeout in seconds

    Returns:
        Cached or computed value
    """
    try:
        value = cache_get(key)
        if value is not None:
            return value

        value = default_callable()
        cache_set(key, value, timeout)
        return value
    except Exception as e:
        # Log error in production and return computed value
        print(f"Cache get_or_set error for key '{key}': {e}")
        return default_callable()


# Specific cache functions for common use cases


def cache_user_data(user_id: int, data: Any, timeout: Optional[int] = None) -> bool:
    """Cache user-specific data."""
    key = get_cache_key("user", user_id, "data", prefix="cupcake")
    return cache_set(key, data, timeout)


def get_cached_user_data(user_id: int) -> Optional[Any]:
    """Get cached user-specific data."""
    key = get_cache_key("user", user_id, "data", prefix="cupcake")
    return cache_get(key)


def cache_template_data(template_id: int, data: Any, timeout: Optional[int] = None) -> bool:
    """Cache metadata template data."""
    key = get_cache_key("template", template_id, prefix="cupcake")
    return cache_set(key, data, timeout)


def get_cached_template_data(template_id: int) -> Optional[Any]:
    """Get cached metadata template data."""
    key = get_cache_key("template", template_id, prefix="cupcake")
    return cache_get(key)


def invalidate_user_cache(user_id: int) -> bool:
    """Invalidate all cache entries for a user."""
    pattern = get_cache_key("user", user_id, "*", prefix="cupcake")
    return cache_delete_pattern(pattern)


def invalidate_template_cache(template_id: int) -> bool:
    """Invalidate cache entries for a template."""
    pattern = get_cache_key("template", template_id, "*", prefix="cupcake")
    return cache_delete_pattern(pattern)


def cache_ontology_suggestions(
    ontology_type: str, query: str, suggestions: List[dict], timeout: Optional[int] = None
) -> bool:
    """Cache ontology suggestion results."""
    key = get_cache_key("ontology", ontology_type, query, prefix="cupcake")
    return cache_set(key, suggestions, timeout or 3600)  # 1 hour for ontology data


def get_cached_ontology_suggestions(ontology_type: str, query: str) -> Optional[List[dict]]:
    """Get cached ontology suggestions."""
    key = get_cache_key("ontology", ontology_type, query, prefix="cupcake")
    return cache_get(key)
