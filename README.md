# 🔍 Kibana MCP (Model Context Protocol) Server

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-CC--BY--NC--ND--4.0-red.svg)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Modular-green.svg)]()
[![Version](https://img.shields.io/badge/Version-2.0.0-blue.svg)]()

> A powerful, high-performance server that provides seamless access to Kibana and Periscope logs through a unified API. Built with modular architecture, in-memory caching, HTTP/2 support, and OpenTelemetry tracing.

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [What's New in v2.0.0](#-whats-new-in-v200)
- [Setup](#-setup)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
- [Authentication](#-authentication)
- [Running the Server](#-running-the-server)
- [API Reference](#-api-reference)
- [Available Indexes](#-available-indexes)
- [Example Usage](#-example-usage)
- [Troubleshooting](#-troubleshooting)
- [Performance Features](#-performance-features)
- [Architecture](#-architecture)
- [AI Integration](#-ai-integration)
- [License](#-license)

## 🌟 Overview

This project bridges the gap between your applications and Kibana/Periscope logs by providing:

1. **Modular Architecture**: Clean separation of concerns with dedicated modules for clients, services, and API layers
2. **Dual Interface Support**: Both Kibana (KQL) and Periscope (SQL) querying
3. **Multi-Index Access**: Query across 9 different log indexes (1.3+ billion logs)
4. **Performance Optimized**: In-memory caching, HTTP/2, and connection pooling
5. **Timezone-Aware**: Full support for international timezones (IST, UTC, PST, etc.)
6. **Production-Ready**: Comprehensive error handling, retry logic, and observability

## ✨ Features

### Core Features
- **Simple API**: Easy-to-use RESTful endpoints for log searching and analysis
- **Dual Log System Support**: 
  - **Kibana**: KQL-based querying for application logs
  - **Periscope**: SQL-based querying for HTTP access logs
- **Multi-Index Support**: Access to 9 indexes with 1.3+ billion logs
- **Flexible Authentication**: API-based token management for both Kibana and Periscope
- **Time-Based Searching**: Absolute and relative time ranges with full timezone support
- **Real-Time Streaming**: Monitor logs as they arrive

### Performance Features (New in v2.0.0)
- **⚡ In-Memory Caching**: 
  - Schema cache: 1 hour TTL
  - Search cache: 5 minutes TTL
- **🚀 HTTP/2 Support**: Multiplexed connections for faster requests
- **🔄 Connection Pooling**: 200 max connections, 50 keepalive
- **📊 OpenTelemetry Tracing**: Distributed tracing for monitoring and debugging
- **🌍 Timezone-Aware**: Support for any IANA timezone without manual UTC conversion

### AI & Analysis Features
- **🧠 AI-Powered Analysis**: Intelligent log summarization using [Neurolink](https://www.npmjs.com/package/@juspay/neurolink)
- **Smart Chunking**: Automatic handling of large log sets
- **Pattern Analysis**: Tools to identify log patterns and extract errors
- **Cross-Index Correlation**: Track requests across multiple log sources

## 🆕 What's New in v2.0.0

### Modular Architecture
- ✅ Clean separation: `clients/`, `services/`, `api/`, `models/`, `utils/`
- ✅ Improved testability and maintainability
- ✅ Better error handling and logging
- ✅ Type-safe with Pydantic models

### Performance Enhancements
- ✅ In-memory caching reduces API calls
- ✅ HTTP/2 support for better throughput
- ✅ Connection pooling for efficiency
- ✅ OpenTelemetry tracing for observability

### Multi-Index Support
- ✅ **9 indexes accessible** (7 with active data)
- ✅ **1.3+ billion logs** available
- ✅ Index discovery and selection API
- ✅ Universal `timestamp` field compatibility

### Enhanced Timezone Support
- ✅ Periscope queries with timezone parameter
- ✅ No manual UTC conversion needed
- ✅ Support for IST, UTC, PST, and all IANA timezones

### Configuration Improvements
- ✅ Optimized `config.yaml` (36% smaller)
- ✅ Dynamic configuration via API
- ✅ Only essential parameters included

## 🚀 Setup

### Prerequisites

- **Python 3.8+**
- **Access to Kibana instance** (for Kibana features)
- **Access to Periscope instance** (optional, for Periscope features)
- **Authentication tokens** for the services you want to use

### Installation

1. **Clone this repository**:
   ```bash
   git clone https://github.com/gaharivatsa/KIBANA_SERVER.git
   cd KIBANA_SERVER
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv KIBANA_E
   
   # On macOS/Linux
   source KIBANA_E/bin/activate
   
   # On Windows
   KIBANA_E\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Make the start script executable**:
   ```bash
   chmod +x ./run_kibana_mcp.sh
   ```

5. **Optional: Set up AI-powered log analysis**:
   ```bash
   # Install Node.js if not already installed (required for Neurolink)
   # Visit https://nodejs.org/ or use your package manager
   
   # Set your AI provider API key
   export GOOGLE_AI_API_KEY="your-google-ai-api-key"  # Recommended (free tier)
   # OR export OPENAI_API_KEY="your-openai-key"
   
   # Neurolink will be automatically set up when you start the server
   ```

### Configuration

The server comes with an optimized `config.yaml` that works out of the box. Key settings:

```yaml
elasticsearch:
  host: ""  # Set via API or environment
  timestamp_field: "timestamp"  # ✅ Works for ALL 9 indexes
  verify_ssl: true

mcp_server:
  host: "0.0.0.0"
  port: 8000
  log_level: "info"

periscope:
  host: ""  # Default: periscope.breezesdk.store

timeouts:
  kibana_request_timeout: 30
```

**Dynamic Configuration** (optional):
```bash
curl -X POST http://localhost:8000/api/set_config \
  -H "Content-Type: application/json" \
  -d '{
    "configs_to_set": {
      "elasticsearch.host": "your-kibana.example.com",
      "mcp_server.log_level": "debug"
    }
  }'
```

## 🔐 Authentication

### Kibana Authentication

**Set via API (Recommended)**:
```bash
curl -X POST http://localhost:8000/api/set_auth_token \
  -H "Content-Type: application/json" \
  -d '{"auth_token":"YOUR_KIBANA_JWT_TOKEN"}'
```

**How to Get Your Token**:
1. Log in to Kibana in your browser
2. Open developer tools (F12)
3. Go to Application → Cookies
4. Find the authentication cookie (e.g., JWT token)
5. Copy the complete value

### Periscope Authentication

```bash
curl -X POST http://localhost:8000/api/set_periscope_auth_token \
  -H "Content-Type: application/json" \
  -d '{"auth_token":"YOUR_PERISCOPE_AUTH_TOKEN"}'
```

**How to Get Periscope Token**:
1. Log in to Periscope in your browser
2. Open developer tools (F12)
3. Go to Application → Cookies
4. Find the `auth_tokens` cookie
5. Copy its value (base64 encoded)

## 🖥️ Running the Server

Start the server:

```bash
./run_kibana_mcp.sh
```

The server will be available at `http://localhost:8000`

**Health Check**:
```bash
curl http://localhost:8000/api/health
```

Response:
```json
{
  "success": true,
  "message": "Server is healthy",
  "version": "2.0.0",
  "status": "ok"
}
```

## 📡 API Reference

### Kibana Endpoints

| Endpoint | Description | Method |
|----------|-------------|--------|
| `/api/health` | Health check | GET |
| `/api/set_auth_token` | Set Kibana authentication | POST |
| `/api/discover_indexes` | List available indexes | GET |
| `/api/set_current_index` | Select index for searches | POST |
| `/api/search_logs` | **MAIN** - Search logs with KQL | POST |
| `/api/get_recent_logs` | Get most recent logs | POST |
| `/api/extract_errors` | Extract error logs | POST |
| `/api/summarize_logs` | 🧠 AI-powered analysis | POST |

### Periscope Endpoints

| Endpoint | Description | Method |
|----------|-------------|--------|
| `/api/set_periscope_auth_token` | Set Periscope authentication | POST |
| `/api/get_periscope_streams` | List available streams | GET |
| `/api/get_periscope_stream_schema` | Get stream schema | POST |
| `/api/get_all_periscope_schemas` | Get all schemas | GET |
| `/api/search_periscope_logs` | **MAIN** - Search with SQL | POST |
| `/api/search_periscope_errors` | Find HTTP errors | POST |

### Utility Endpoints

| Endpoint | Description | Method |
|----------|-------------|--------|
| `/api/set_config` | Dynamic configuration | POST |

## 🗂️ Available Indexes

The server provides access to 9 log indexes (7 with active data):

### Active Indexes

| Index Pattern | Total Logs | Use Case | Key Fields |
|---------------|------------|----------|------------|
| **breeze-v2\*** | 1B+ (73.5%) | Backend API, payments | `session_id`, `message`, `level` |
| **envoy-edge\*** | 137M+ (10%) | HTTP traffic, errors | `response_code`, `path`, `duration` |
| **istio-logs-v2\*** | 137M+ (10%) | Service mesh | `level`, `message` |
| **squid-logs\*** | 7M+ (0.5%) | Proxy traffic | `level`, `message` |
| **wallet-lrw\*** | 887K+ (0.1%) | Wallet transactions | `order_id`, `txn_uuid` |
| **analytics-dashboard-v2\*** | 336K+ | Analytics API | `auth`, `headers` |
| **rewards-engine-v2\*** | 7.5K+ | Rewards system | `level`, `message` |

### Empty Indexes
- `wallet-product-v2*` - No data
- `core-ledger-v2*` - No data

**Total**: ~1.3 Billion logs across all indexes

## 📝 Example Usage

### 1. Discover and Set Index

```bash
# Discover available indexes
curl -X GET http://localhost:8000/api/discover_indexes

# Response:
{
  "success": true,
  "indexes": ["breeze-v2*", "envoy-edge*", "istio-logs-v2*", ...],
  "count": 9
}

# Set the index to use
curl -X POST http://localhost:8000/api/set_current_index \
  -H "Content-Type: application/json" \
  -d '{"index_pattern": "breeze-v2*"}'
```

### 2. Search Logs (Kibana)

**Basic Search**:
```bash
curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "error OR exception",
    "max_results": 50,
    "sort_by": "timestamp",
    "sort_order": "desc"
  }'
```

**Search with Time Range (Timezone-Aware)**:
```bash
curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "payment AND failed",
    "start_time": "2025-10-14T09:00:00+05:30",
    "end_time": "2025-10-14T17:00:00+05:30",
    "max_results": 100
  }'
```

**Session-Based Search**:
```bash
curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "PcuUFbLIPLlTbBMwQXl9Y",
    "max_results": 200,
    "sort_by": "timestamp",
    "sort_order": "asc"
  }'
```

### 3. Search Periscope Logs (SQL)

**Find 5XX Errors**:
```bash
curl -X POST http://localhost:8000/api/search_periscope_logs \
  -H "Content-Type: application/json" \
  -d '{
    "sql_query": "SELECT * FROM \"envoy_logs\" WHERE status_code >= '\''500'\'' AND status_code < '\''600'\''",
    "start_time": "1h",
    "max_results": 50
  }'
```

**Search with Timezone (NEW!)**:
```bash
curl -X POST http://localhost:8000/api/search_periscope_logs \
  -H "Content-Type: application/json" \
  -d '{
    "sql_query": "SELECT * FROM \"envoy_logs\" WHERE status_code >= '\''500'\''",
    "start_time": "2025-10-14 09:00:00",
    "end_time": "2025-10-14 13:00:00",
    "timezone": "Asia/Kolkata",
    "max_results": 100
  }'
```

**Quick Error Search**:
```bash
curl -X POST http://localhost:8000/api/search_periscope_errors \
  -H "Content-Type: application/json" \
  -d '{
    "hours": 1,
    "stream": "envoy_logs",
    "error_codes": "5%",
    "timezone": "Asia/Kolkata"
  }'
```

### 4. AI-Powered Analysis

```bash
curl -X POST http://localhost:8000/api/summarize_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "error",
    "max_results": 50,
    "start_time": "1h"
  }'
```

**Response** (example):
```json
{
  "success": true,
  "analysis": {
    "summary": "Analysis of 42 error logs showing payment processing failures",
    "key_insights": [
      "Payment gateway returned 503 errors for 8 transactions",
      "Retry mechanism activated in 67% of failed cases"
    ],
    "errors": [
      "PaymentGatewayError: Service temporarily unavailable (503)"
    ],
    "function_calls": ["processPayment()", "retryTransaction()"],
    "recommendations": [
      "Implement circuit breaker for payment gateway",
      "Add monitoring alerts for gateway health"
    ]
  }
}
```

### 5. Cross-Index Correlation

Track a request across multiple indexes:

```bash
# Step 1: Check HTTP layer (envoy-edge)
curl -X POST http://localhost:8000/api/set_current_index \
  -H "Content-Type: application/json" \
  -d '{"index_pattern": "envoy-edge*"}'

curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "x_session_id:abc123",
    "max_results": 50
  }'

# Step 2: Check backend processing (breeze-v2)
curl -X POST http://localhost:8000/api/set_current_index \
  -H "Content-Type: application/json" \
  -d '{"index_pattern": "breeze-v2*"}'

curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "abc123",
    "max_results": 200,
    "sort_order": "asc"
  }'
```

## 🔧 Troubleshooting

### Common Issues

#### 1. Timestamp Field Errors

**Problem**: "No mapping found for [timestamp] in order to sort on"

**Solution**: The server uses `timestamp` field which works for all indexes. This error should not occur in v2.0.0.

If you see it:
```bash
curl -X POST http://localhost:8000/api/set_config \
  -H "Content-Type: application/json" \
  -d '{
    "configs_to_set": {
      "elasticsearch.timestamp_field": "@timestamp"
    }
  }'
```

#### 2. Authentication Errors (401)

**Problem**: "Unauthorized" or "Invalid token"

**Solution**:
- Token expired - get a fresh token from browser
- Re-authenticate using `/api/set_auth_token`

#### 3. No Results Returned

**Checklist**:
1. ✅ Is the correct index set?
2. ✅ Is the time range correct?
3. ✅ Try a broader query (`"*"`)
4. ✅ Check timezone offset

#### 4. Slow Queries

**Solutions**:
- Reduce `max_results`
- Narrow time range
- Add specific query terms
- Check if caching is working (should be faster on repeated queries)

### Testing

```bash
# Test Kibana connectivity
curl -X POST http://localhost:8000/api/search_logs \
  -H "Content-Type: application/json" \
  -d '{"query_text": "*", "max_results": 1}'

# Test Periscope connectivity
curl -X GET http://localhost:8000/api/get_periscope_streams
```

## ⚡ Performance Features

### In-Memory Caching

**Automatic caching** reduces load on backend systems:

- **Schema Cache**: 1 hour TTL (Periscope stream schemas)
- **Search Cache**: 5 minutes TTL (recent queries)

**Benefits**:
- Faster repeated queries
- Reduced API calls
- Lower backend load

### HTTP/2 Support

- Multiplexed connections
- Faster concurrent requests
- Better throughput for parallel queries

### Connection Pooling

- **Max connections**: 200
- **Keepalive connections**: 50
- Efficient connection reuse
- Reduced latency

### OpenTelemetry Tracing

- Distributed request tracing
- Performance monitoring
- Debug distributed issues
- Track request flow across components

## 🏗️ Architecture

### Modular Structure

```
KIBANA_SERVER/
├── main.py                    # Server entry point
├── config.yaml                # Configuration
├── requirements.txt           # Dependencies
├── src/
│   ├── api/
│   │   ├── app.py            # FastAPI application
│   │   └── http/
│   │       └── routes.py     # API endpoints
│   ├── clients/
│   │   ├── kibana_client.py  # Kibana API client
│   │   ├── periscope_client.py # Periscope API client
│   │   ├── http_manager.py   # HTTP/2 + pooling
│   │   └── retry_manager.py  # Retry logic
│   ├── services/
│   │   └── log_service.py    # Business logic
│   ├── models/
│   │   ├── requests.py       # Request models
│   │   └── responses.py      # Response models
│   ├── utils/
│   │   └── cache.py          # Caching utilities
│   ├── observability/
│   │   └── tracing.py        # OpenTelemetry
│   ├── security/
│   │   └── sanitizers.py     # Input validation
│   └── core/
│       ├── config.py         # Configuration
│       ├── constants.py      # Constants
│       └── logging_config.py # Logging
└── AI_rules.txt              # Generic AI guide
```

### Legacy vs Modular

| Feature | Legacy (v1.x) | Modular (v2.0) |
|---------|---------------|----------------|
| Architecture | Monolithic | Modular |
| Caching | ❌ None | ✅ In-memory |
| HTTP | HTTP/1.1 | ✅ HTTP/2 |
| Tracing | ❌ None | ✅ OpenTelemetry |
| Connection Pool | ❌ Basic | ✅ Advanced |
| Timezone Support | ⚠️ Manual | ✅ Automatic |
| Config Management | ⚠️ Static | ✅ Dynamic |
| Error Handling | ⚠️ Basic | ✅ Comprehensive |

## 🤖 AI Integration

### For AI Assistants

Use the provided `AI_rules.txt` for generic product documentation or `AI_rules_file.txt` for company-specific usage.

**Key Requirements**:
- ✅ Always authenticate first
- ✅ Discover and set index before searching
- ✅ Use `timestamp` field for sorting
- ✅ Include session_id in queries when tracking sessions
- ✅ Use ISO timestamps with timezone

### Example AI Workflow

1. **Authenticate**:
   ```bash
   POST /api/set_auth_token
   ```

2. **Discover Indexes**:
   ```bash
   GET /api/discover_indexes
   ```

3. **Set Index**:
   ```bash
   POST /api/set_current_index
   ```

4. **Search Logs**:
   ```bash
   POST /api/search_logs
   ```

5. **Analyze (Optional)**:
   ```bash
   POST /api/summarize_logs
   ```

For complete AI integration instructions, refer to `AI_rules.txt` (generic) or `AI_rules_file.txt` (company-specific).

## 📚 Documentation

- **AI_rules.txt** - Generic product usage guide
- **AI_rules_file.txt** - Company-specific usage (internal)
- **CONFIG_USAGE_ANALYSIS.md** - Configuration reference (deleted, info in this README)
- **KIBANA_INDEXES_COMPLETE_ANALYSIS.md** - Index details (deleted, info in this README)

## 🔄 Migration from v1.x

If upgrading from v1.x:

1. **Update imports**: Change from `kibana_mcp_server.py` to `main.py`
2. **Update config**: Remove unused parameters (see `config.yaml`)
3. **Update queries**: Use `timestamp` field instead of `@timestamp` or `start_time`
4. **Test endpoints**: All endpoints remain compatible
5. **Enjoy performance**: Automatic caching and HTTP/2 benefits

## 📊 Performance Benchmarks

- **Cache Hit Rate**: ~80% for repeated queries
- **Response Time**: 30-50% faster with HTTP/2
- **Connection Reuse**: 90%+ with pooling
- **Memory Usage**: <200MB with full cache

## 🤝 Contributing

This is a proprietary project. For issues or feature requests, contact the maintainers.

## 📜 License

This project is licensed under the **Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License (CC BY-NC-ND 4.0)**.

[![License: CC BY-NC-ND 4.0](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-nd/4.0/)

**This license requires that reusers**:
- ✅ Give appropriate credit (Attribution)
- ❌ Do not use for commercial purposes (NonCommercial)
- ❌ Do not distribute modified versions (NoDerivatives)

For more information, see the [LICENSE](LICENSE) file.

---

**Version**: 2.0.0 (Modular)  
**Last Updated**: October 2025  
**Total Logs**: 1.3+ Billion  
**Indexes**: 9 (7 active)  
**Status**: Production Ready ✅
