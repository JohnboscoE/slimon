#!/usr/bin/env bash
# Vercel "Ignored Build Step": exit 1 to build, exit 0 to skip.
#
# /app is rendered from the decision log that is bundled at build time, so the deployed site only
# moves forward when a build runs. The agent commits the log about once an hour (and once more when
# a run hands over), which is a fine cadence to deploy on: ~20 builds a day, well inside the free
# allowance. Commits that touch neither the site nor the log - a state-only commit, say - are skipped.
set -u

changed() { ! git diff --quiet HEAD^ HEAD -- "$@"; }

if changed .; then
  echo "web/ changed - building"
  exit 1
fi

if changed ../logs; then
  echo "decision log changed - building so /app shows the newest ticks"
  exit 1
fi

echo "nothing that affects the site changed - skipping this build"
exit 0
