#!/bin/bash
# Helper script to build JustHTML with mypyc compilation
#
# Usage:
#   ./build_mypyc.sh          # Build with mypyc
#   ./build_mypyc.sh clean    # Clean build artifacts
#   ./build_mypyc.sh test     # Build and run tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}JustHTML mypyc Build Script${NC}"
echo -e "${GREEN}======================================${NC}"

# Handle clean command
if [ "$1" == "clean" ]; then
    echo -e "${YELLOW}Cleaning build artifacts...${NC}"
    rm -rf build/ dist/ *.egg-info src/*.egg-info
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.so" -delete 2>/dev/null || true
    find . -type f -name "*.pyd" -delete 2>/dev/null || true
    echo -e "${GREEN}Clean complete!${NC}"
    exit 0
fi

# Install mypyc dependencies if needed
if ! python -c "import mypyc" 2>/dev/null; then
    echo -e "${YELLOW}Installing mypyc dependencies...${NC}"
    pip install -e ".[mypyc]"
fi

# Build with mypyc
echo -e "${YELLOW}Building with mypyc (this may take a few minutes)...${NC}"
JUSTHTML_USE_MYPYC=1 pip install -e . --no-build-isolation -v

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Build complete!${NC}"
echo -e "${GREEN}======================================${NC}"

# Check if compiled modules were created
if ls src/justhtml/*.so 2>/dev/null || ls src/justhtml/*.pyd 2>/dev/null; then
    echo -e "${GREEN}Compiled modules created:${NC}"
    ls -lh src/justhtml/*.so 2>/dev/null || ls -lh src/justhtml/*.pyd 2>/dev/null
else
    echo -e "${RED}Warning: No compiled modules found!${NC}"
fi

# Run tests if requested
if [ "$1" == "test" ]; then
    echo -e "${YELLOW}Running test suite...${NC}"
    python run_tests.py
fi
