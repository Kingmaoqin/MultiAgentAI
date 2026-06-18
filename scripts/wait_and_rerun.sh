#!/usr/bin/env bash
# Wait for all RAVEL experiment processes to finish, then launch corrected runs.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TAU2_DIR="$(dirname "$SCRIPT_DIR")/worktrees/tau2-clean"

echo "$(date): Waiting for current experiment processes to finish..."
while ps aux | grep -q "run_ravel_exp\|run_dev_baseline" | grep -v grep; do
  n=$(ps aux | grep "run_ravel_exp\|run_dev_baseline" | grep -v grep | wc -l)
  echo "$(date): $n processes still running, sleeping 60s..."
  sleep 60
done

echo "$(date): All current processes finished. Starting corrected RAVEL runs..."

cd "$TAU2_DIR"
for DOMAIN in airline retail telecom; do
  echo "$(date): Running corrected RAVEL for domain=$DOMAIN"
  bash "$SCRIPT_DIR/run_ravel_corrected.sh" "$DOMAIN" \
    >> /home/xqin5/multiaiagent/results/ravel_corrected/rerun.log 2>&1
  echo "$(date): Finished $DOMAIN"
done

echo "$(date): All corrected runs complete!"
PYTHONPATH=/home/xqin5/multiaiagent/src python3 "$SCRIPT_DIR/analyze_results.py" --corrected \
  >> /home/xqin5/multiaiagent/results/ravel_corrected/analysis.txt 2>&1
echo "$(date): Analysis saved to results/ravel_corrected/analysis.txt"
