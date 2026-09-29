#!/bin/sh
# Print what is needed to understand a stuck or failed `make up`.
cd "$(dirname "$0")/../.."
H=""; [ -f infra/.host-network ] && H="-f infra/docker-compose.host.yml"
C="docker compose -f infra/docker-compose.yml $H --env-file infra/.env"
echo
echo "=================== PianoForge diagnostics ==================="
echo "--- services"
$C ps -a --format '{{.Service}}: {{.Status}}'
for s in migrate storage-init api; do
  echo "--- log: $s"
  $C logs --no-log-prefix --tail=15 "$s" 2>&1
done
echo "--- name resolution and reachability from an api container"
$C run --rm --no-deps -T --entrypoint python api -c "
import socket, sys
for host, port in (('postgres', 5432), ('redis', 6379), ('storage', 9000)):
    try:
        ip = socket.gethostbyname(host)
        s = socket.create_connection((ip, port), timeout=5); s.close()
        print(host, ip, 'reachable')
    except Exception as e:
        print(host, 'FAILED', repr(e))
" 2>&1 | tail -5
echo "--- docker"
docker version --format 'server {{.Server.Version}}' 2>&1
docker compose version 2>&1
echo "--- resources"
nproc | sed 's/^/cpus: /'; free -m | sed -n 2p; df -h / | tail -1
echo "==============================================================="
