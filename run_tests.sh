#!/bin/bash
# Test runner script for QC-Studio UI tests

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}QC-Studio UI Test Suite${NC}\n"

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest is not installed${NC}"
    echo "Install it with: pip install -r requirements-test.txt"
    exit 1
fi

# Parse command line arguments
TEST_TYPE="${1:-all}"
COVERAGE="${2:-false}"

case $TEST_TYPE in
    all)
        echo -e "${GREEN}Running all tests...${NC}\n"
        if [ "$COVERAGE" = "--cov" ]; then
            pytest ui/tests/ --cov=ui --cov-report=html --cov-report=term-missing -v
        else
            pytest ui/tests/ -v
        fi
        ;;
    models)
        echo -e "${GREEN}Running model tests...${NC}\n"
        pytest ui/tests/test_models.py -v
        ;;
    utils)
        echo -e "${GREEN}Running utility tests...${NC}\n"
        pytest ui/tests/test_utils.py -v
        ;;
    ui)
        echo -e "${GREEN}Running UI tests...${NC}\n"
        pytest ui/tests/test_ui.py -v
        ;;
    layout)
        echo -e "${GREEN}Running layout tests...${NC}\n"
        pytest ui/tests/test_layout.py -v
        ;;
    quick)
        echo -e "${GREEN}Running quick tests (no slow tests)...${NC}\n"
        pytest ui/tests/ -v -m "not slow"
        ;;
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo "Usage: $0 [all|models|utils|ui|layout|quick] [--cov]"
        exit 1
        ;;
esac

echo -e "\n${GREEN}Tests completed!${NC}"
