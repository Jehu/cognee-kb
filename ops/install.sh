#!/usr/bin/env bash
set -euo pipefail
for name in local cloud; do
  cp "ops/de.michelyweb.kb.worker-${name}.plist" ~/Library/LaunchAgents/
  launchctl unload ~/Library/LaunchAgents/de.michelyweb.kb.worker-${name}.plist 2>/dev/null || true
  launchctl load ~/Library/LaunchAgents/de.michelyweb.kb.worker-${name}.plist
done
echo "Beide Worker installiert. Logs: var/<instanz>/worker.log"
