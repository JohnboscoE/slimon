#!/usr/bin/env bash
# Vercel "Ignored Build Step": exit 1 to build, exit 0 to skip.
#
# The agent commits a log line every five minutes, and a deployment per tick would exhaust the
# free daily allowance. So: build whenever the site's own files changed, and otherwise only in the
# first five minutes of each hour, which keeps /app at most an hour behind the log.
set -u

if ! git diff --quiet HEAD^ HEAD -- .; then
  echo "web/ changed since the last commit - building"
  exit 1
fi

minute=$((10#$(date -u +%M)))
if [ "$minute" -lt 5 ]; then
  echo "hourly refresh of the decision log - building"
  exit 1
fi

echo "log-only commit and not the top of the hour - skipping this build"
exit 0
