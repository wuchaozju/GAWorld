#!/bin/bash
# Auto-restart unhealthy Docker Compose services.
# Install as a cron job: crontab -e
#   */5 * * * * /home/justin/fos/docker/auto-recover.sh >> /home/justin/fos/auto-recover.log 2>&1

cd "$(dirname "$0")/.." || exit 1

UNHEALTHY=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    svc = json.loads(line)
    if svc.get('Health') == 'unhealthy':
        print(svc['Service'])
" 2>/dev/null)

if [ -n "$UNHEALTHY" ]; then
    echo "[$(date)] Restarting unhealthy services: $UNHEALTHY"
    echo "$UNHEALTHY" | xargs docker compose restart
    echo "[$(date)] Restart complete"
fi
