"""
Application Constants

Centralized constants used throughout the application.
"""

# Application metadata
APP_NAME = "kibana-mcp-server"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Kibana MCP Server - Modular Architecture"

# HTTP status codes
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_SERVICE_UNAVAILABLE = 503

# Default timeouts (seconds)
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_CONNECT_TIMEOUT = 5
DEFAULT_RETRY_TIMEOUT = 60

# Rate limiting defaults
DEFAULT_SEARCH_RATE_LIMIT = 100  # requests per minute
DEFAULT_AUTH_RATE_LIMIT = 10     # requests per minute
DEFAULT_CONFIG_RATE_LIMIT = 20   # requests per minute

# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF = 1.0
DEFAULT_MAX_BACKOFF = 30.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_JITTER_FACTOR = 0.3

# Log search defaults
DEFAULT_MAX_LOGS = 1000
DEFAULT_TIME_RANGE = "1d"
DEFAULT_SORT_ORDER = "desc"

# Timestamp field names (try in order)
TIMESTAMP_FIELDS = ["timestamp", "@timestamp", "start_time"]

# Authentication contexts
AUTH_CONTEXT_KIBANA = "kibana"
AUTH_CONTEXT_PERISCOPE = "periscope"

# Validation limits
MAX_QUERY_LENGTH = 5000
MAX_SESSION_ID_LENGTH = 200
MAX_ORDER_ID_LENGTH = 100
MAX_INDEX_PATTERN_LENGTH = 100
MAX_FIELD_NAME_LENGTH = 100

# Periscope stream names - No hardcoded list (generic for all companies)
# Stream name validation happens via SQL identifier sanitization
# This allows any customer's stream names while preventing SQL injection

# KQL and SQL dangerous keywords
DANGEROUS_SQL_KEYWORDS = [
    'drop', 'delete', 'insert', 'update', 'create',
    'alter', 'truncate', 'exec', 'execute', 'union',
    'script', 'javascript', '<script', 'eval'
]

# HTTP headers
HEADER_KBN_VERSION = "kbn-version"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_AUTHORIZATION = "Authorization"
HEADER_REQUEST_ID = "X-Request-ID"
HEADER_RETRY_AFTER = "Retry-After"

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_TEXT = "text/plain"

# Log levels
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_CRITICAL = "CRITICAL"

# Time units for parsing
TIME_UNITS = {
    'h': 'hours',
    'd': 'days',
    'w': 'weeks',
    'm': 'months',
}

# Elasticsearch/Kibana defaults
DEFAULT_KIBANA_VERSION = "7.10.2"
DEFAULT_KIBANA_BASE_PATH = "/_plugin/kibana"
DEFAULT_ES_INDEX_PREFIX = ""

# Connection pool limits
MAX_KEEPALIVE_CONNECTIONS = 10
MAX_CONNECTIONS = 20

# Cache settings
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes

# Periscope defaults
DEFAULT_PERISCOPE_ORG = "default"
DEFAULT_PERISCOPE_MAX_RESULTS = 50

# Error messages
ERROR_NO_AUTH_TOKEN = "No authentication token available. Please set it via API, environment variable, or config."
ERROR_AUTH_FAILED = "Authentication failed. Check your authentication token."
ERROR_RATE_LIMIT_EXCEEDED = "Rate limit exceeded. Please try again later."
ERROR_INVALID_CONFIG = "Invalid configuration"
ERROR_TIMEOUT = "Operation timed out"
ERROR_SESSION_NOT_FOUND = "Session ID not found"
ERROR_INDEX_NOT_FOUND = "Index not found"

# Success messages
SUCCESS_TOKEN_SET = "Authentication token set successfully"
SUCCESS_CONFIG_UPDATED = "Configuration updated successfully"
SUCCESS_INDEX_SET = "Index pattern set successfully"
