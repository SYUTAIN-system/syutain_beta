#!/bin/bash
# PDL Phase 1 Setup Script
echo "=== PDL Phase 1 Setup ==="
echo ""
echo "Add this line to crontab (crontab -e):"
echo "*/10 * * * * /bin/zsh -l -c '$HOME/syutain_beta/pdl/worker.sh'"
echo ""
echo "To verify: crontab -l | grep pdl"
