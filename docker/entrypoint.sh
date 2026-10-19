#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py ensure_admin

if [ "${SERVCHART_DEMO:-0}" = "1" ]; then
  python manage.py load_demo
fi

# Map the hub's own host when the Docker socket (or a socket proxy) is available.
if [ "${SERVCHART_LOCAL_AGENT:-1}" = "1" ] && { [ -S /var/run/docker.sock ] || [ -n "$DOCKER_HOST" ]; }; then
  echo "Local collector enabled (mapping this host)."
  python manage.py local_agent &
else
  echo "Local collector disabled (no Docker socket mounted)."
fi

exec gunicorn servchart.wsgi:application \
  --bind "0.0.0.0:${SERVCHART_PORT:-8484}" \
  --workers "${SERVCHART_WORKERS:-2}" \
  --access-logfile - \
  --forwarded-allow-ips "${SERVCHART_FORWARDED_ALLOW_IPS:-127.0.0.1}"
