#!/bin/bash

# Kibana MCP Server - Modular Architecture Startup Script
# Copyright (c) 2025 [Harivatsa G A]. All rights reserved.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}🚀 Kibana MCP Server (Modular v2.0.0)${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Configuration
VENV_DIR="${VENV_DIR:-KIBANA_E}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_FILE="${LOG_FILE:-modular_server.log}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --background|-b)
            BACKGROUND=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --port PORT        Port to bind to (default: 8000)"
            echo "  --host HOST        Host to bind to (default: 0.0.0.0)"
            echo "  --log-level LEVEL  Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)"
            echo "  --background, -b   Run server in background"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  PORT               Override default port"
            echo "  HOST               Override default host"
            echo "  LOG_LEVEL          Override default log level"
            echo "  VENV_DIR           Virtual environment directory (default: KIBANA_E)"
            echo ""
            echo "Examples:"
            echo "  $0                          # Start on default port 8000"
            echo "  $0 --port 8001              # Start on port 8001"
            echo "  $0 --background             # Run in background"
            echo "  PORT=9000 $0                # Use environment variable"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}❌ Virtual environment not found: $VENV_DIR${NC}"
    echo -e "${YELLOW}💡 Run ./setup_dev.sh to set up the environment${NC}"
    exit 1
fi

# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo -e "${RED}❌ main.py not found${NC}"
    echo "Make sure you're running this script from the project root directory"
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment: $VENV_DIR${NC}"
source "$VENV_DIR/bin/activate"

# Check if required packages are installed
echo -e "${BLUE}📦 Checking dependencies...${NC}"
python3 -c "import fastapi, uvicorn, pydantic, loguru, httpx" 2>/dev/null || {
    echo -e "${RED}❌ Missing dependencies${NC}"
    echo -e "${YELLOW}💡 Run: pip install -r requirements.txt${NC}"
    exit 1
}

echo -e "${GREEN}✅ Dependencies OK${NC}"
echo ""

# Display configuration
echo -e "${BLUE}⚙️  Configuration:${NC}"
echo -e "   Host: ${GREEN}$HOST${NC}"
echo -e "   Port: ${GREEN}$PORT${NC}"
echo -e "   Log Level: ${GREEN}$LOG_LEVEL${NC}"
echo -e "   Background: ${GREEN}${BACKGROUND:-false}${NC}"
echo ""

# Check if port is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠️  Port $PORT is already in use${NC}"
    echo -e "${YELLOW}Kill existing process? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Killing process on port $PORT...${NC}"
        lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
        sleep 2
        echo -e "${GREEN}✅ Port $PORT is now free${NC}"
    else
        echo -e "${RED}❌ Cannot start server - port in use${NC}"
        exit 1
    fi
fi

echo -e "${BLUE}=========================================${NC}"
echo -e "${GREEN}🚀 Starting Kibana MCP Server...${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Build the command
CMD="python3 main.py --host $HOST --port $PORT --log-level $LOG_LEVEL"

if [ "$BACKGROUND" = true ]; then
    # Run in background
    echo -e "${BLUE}Running in background mode...${NC}"
    nohup $CMD > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo $SERVER_PID > modular_server.pid

    # Wait a moment and check if server started
    sleep 3

    if kill -0 $SERVER_PID 2>/dev/null; then
        echo -e "${GREEN}✅ Server started successfully!${NC}"
        echo ""
        echo -e "${BLUE}📊 Server Information:${NC}"
        echo -e "   PID: ${GREEN}$SERVER_PID${NC}"
        echo -e "   Log file: ${GREEN}$LOG_FILE${NC}"
        echo -e "   API URL: ${GREEN}http://$HOST:$PORT${NC}"
        echo -e "   API Docs: ${GREEN}http://localhost:$PORT/docs${NC}"
        echo ""
        echo -e "${BLUE}📝 Useful Commands:${NC}"
        echo -e "   View logs: ${YELLOW}tail -f $LOG_FILE${NC}"
        echo -e "   Stop server: ${YELLOW}kill $SERVER_PID${NC}"
        echo -e "   Or use: ${YELLOW}kill \$(cat modular_server.pid)${NC}"
        echo ""

        # Show last few log lines
        echo -e "${BLUE}📋 Recent logs:${NC}"
        tail -5 "$LOG_FILE"
    else
        echo -e "${RED}❌ Server failed to start${NC}"
        echo -e "${YELLOW}Check logs: tail -50 $LOG_FILE${NC}"
        exit 1
    fi
else
    # Run in foreground
    echo -e "${BLUE}Running in foreground mode...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo ""
    echo -e "${BLUE}📊 Server will be available at:${NC}"
    echo -e "   API: ${GREEN}http://$HOST:$PORT${NC}"
    echo -e "   Docs: ${GREEN}http://localhost:$PORT/docs${NC}"
    echo ""
    echo -e "${BLUE}=========================================${NC}"
    echo ""

    # Run the server
    exec $CMD
fi
