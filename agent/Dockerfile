# ServChart agent: standard library only, no dependencies.
FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY servchart_agent /app/servchart_agent
# Runs as root by default so it can read /var/run/docker.sock on any host.
# To run unprivileged: --user 65534 --group-add $(stat -c %g /var/run/docker.sock)
ENTRYPOINT ["python", "-m", "servchart_agent"]
