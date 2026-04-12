#!/usr/bin/env zsh
set -eu
cd /home/kth/SecBreak
python3 -u pipeline_watchdog.py >> logs/watchdog_cron.log 2>&1
