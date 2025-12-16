#!/bin/bash
# Compare performance between pure Python and mypyc-compiled versions of JustHTML
#
# Usage:
#   ./compare_pure_vs_compiled.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=================================================================${NC}"
echo -e "${BLUE}JustHTML: Pure Python vs Mypyc Performance Comparison${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""

# Store results
RESULTS_FILE="benchmark_results_$(date +%Y%m%d_%H%M%S).txt"

echo -e "${YELLOW}Step 1: Building Pure Python version${NC}"
echo "----------------------------------------------------------------------"
echo "Removing any compiled .so files..."
find src/justhtml -name "*.so" -delete 2>/dev/null || true
echo "Reinstalling in pure Python mode..."
uv pip install -e . -q
echo -e "${GREEN}✓ Pure Python version ready${NC}"
echo ""

echo -e "${YELLOW}Step 2: Running Pure Python benchmarks${NC}"
echo "----------------------------------------------------------------------"
PYTHONPATH=src python benchmarks/compare_mypyc.py --mode compiled > /tmp/pure_results.txt 2>&1
cat /tmp/pure_results.txt
cat /tmp/pure_results.txt >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"
echo ""

echo -e "${YELLOW}Step 3: Building Mypyc-compiled version${NC}"
echo "----------------------------------------------------------------------"
echo "Compiling with mypyc (this may take a minute)..."
JUSTHTML_USE_MYPYC=1 uv pip install -e . --no-build-isolation -q
echo -e "${GREEN}✓ Mypyc-compiled version ready${NC}"

# Show what was compiled
if ls src/justhtml/*.so 2>/dev/null; then
    echo ""
    echo "Compiled modules:"
    ls -lh src/justhtml/*.so | awk '{print "  -", $9, "("$5")"}'
fi
echo ""

echo -e "${YELLOW}Step 4: Running Mypyc-compiled benchmarks${NC}"
echo "----------------------------------------------------------------------"
PYTHONPATH=src python benchmarks/compare_mypyc.py --mode compiled > /tmp/compiled_results.txt 2>&1
cat /tmp/compiled_results.txt
cat /tmp/compiled_results.txt >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"
echo ""

echo -e "${YELLOW}Step 5: Calculating speedup${NC}"
echo "----------------------------------------------------------------------"

# Parse results and calculate speedup
PURE_SIMPLE=$(grep "Benchmark 1:" -A2 /tmp/pure_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')
COMPILED_SIMPLE=$(grep "Benchmark 1:" -A2 /tmp/compiled_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')

PURE_COMPLEX=$(grep "Benchmark 2:" -A2 /tmp/pure_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')
COMPILED_COMPLEX=$(grep "Benchmark 2:" -A2 /tmp/compiled_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')

PURE_SERIALIZE=$(grep "Benchmark 3:" -A2 /tmp/pure_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')
COMPILED_SERIALIZE=$(grep "Benchmark 3:" -A2 /tmp/compiled_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')

PURE_ENTITIES=$(grep "Benchmark 4:" -A2 /tmp/pure_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')
COMPILED_ENTITIES=$(grep "Benchmark 4:" -A2 /tmp/compiled_results.txt | grep "Time:" | awk '{print $2}' | tr -d 's')

echo "Speedup Summary:" | tee -a "$RESULTS_FILE"
echo "----------------------------------------------------------------------" | tee -a "$RESULTS_FILE"

if [ -n "$PURE_SIMPLE" ] && [ -n "$COMPILED_SIMPLE" ]; then
    SPEEDUP_SIMPLE=$(python -c "print(f'{$PURE_SIMPLE / $COMPILED_SIMPLE:.2f}x')")
    echo -e "Simple HTML Parsing:    ${GREEN}${SPEEDUP_SIMPLE}${NC}" | tee -a "$RESULTS_FILE"
fi

if [ -n "$PURE_COMPLEX" ] && [ -n "$COMPILED_COMPLEX" ]; then
    SPEEDUP_COMPLEX=$(python -c "print(f'{$PURE_COMPLEX / $COMPILED_COMPLEX:.2f}x')")
    echo -e "Complex HTML Parsing:   ${GREEN}${SPEEDUP_COMPLEX}${NC}" | tee -a "$RESULTS_FILE"
fi

if [ -n "$PURE_SERIALIZE" ] && [ -n "$COMPILED_SERIALIZE" ]; then
    SPEEDUP_SERIALIZE=$(python -c "print(f'{$PURE_SERIALIZE / $COMPILED_SERIALIZE:.2f}x')")
    echo -e "HTML Serialization:     ${GREEN}${SPEEDUP_SERIALIZE}${NC}" | tee -a "$RESULTS_FILE"
fi

if [ -n "$PURE_ENTITIES" ] && [ -n "$COMPILED_ENTITIES" ]; then
    SPEEDUP_ENTITIES=$(python -c "print(f'{$PURE_ENTITIES / $COMPILED_ENTITIES:.2f}x')")
    echo -e "Entity Decoding:        ${GREEN}${SPEEDUP_ENTITIES}${NC}" | tee -a "$RESULTS_FILE"
fi

echo ""
echo -e "${BLUE}=================================================================${NC}"
echo -e "${GREEN}✓ Comparison complete!${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""
echo "Results saved to: $RESULTS_FILE"
echo ""
echo "Note: Serialization and entity decoding show the most improvement"
echo "because those modules (serialize.py, entities.py) are compiled with mypyc."
echo ""

# Cleanup
rm -f /tmp/pure_results.txt /tmp/compiled_results.txt
