"""
Cache Configuration Module

Defines and configures in-memory caches for the application.
This module uses 'cachetools' to provide Time-To-Live (TTL) caching
for frequently accessed, semi-static data.
"""

from cachetools import TTLCache, cached
from functools import partial

# --- Cache Configurations ---

# Cache for Periscope schemas:
# - maxsize=100: Store up to 100 unique stream schemas.
# - ttl=3600: Cache each schema for 1 hour (3600 seconds).
schema_cache = TTLCache(maxsize=100, ttl=3600)

# Cache for Periscope search results:
# - maxsize=1000: Store up to 1000 unique search query results.
# - ttl=300: Cache each search result for 5 minutes (300 seconds).
search_cache = TTLCache(maxsize=1000, ttl=300)


# --- Caching Decorators ---

# These decorators can be applied to functions to enable caching.
# This approach defines a wrapper to correctly apply the 'cached' decorator.

def cache_schema(func):
    """Decorator for caching schema-related functions."""
    return cached(cache=schema_cache)(func)

def cache_search(func):
    """Decorator for caching search-related functions."""
    return cached(cache=search_cache)(func)
