# servchart-agent

The agent for [ServChart](https://github.com/opticodev/servchart), a self-hosted map of your servers, containers and Compose stacks.

It reads this host's Docker state (GET requests only), drops anything sensitive, and sends it to your ServChart hub every 60 seconds. It has no dependencies beyond Python's standard library.

## Run it

**With Docker** (recommended):

```bash
docker run -d --name servchart-agent --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SERVCHART_HUB=https://servchart.example.com \
  -e SERVCHART_TOKEN=sc_... \
  opticodev/servchart-agent:latest
```

**Without Docker**, from PyPI. The user running it needs access to the Docker socket, for example by being in the `docker` group:

```bash
pipx install servchart-agent        # or: pip install servchart-agent
servchart-agent --hub https://servchart.example.com --token sc_...
servchart-agent --stdout            # print what would be sent, send nothing
```

Get the token from the hub: **+ Add host** in the map.

## What it sends

It sends container names, images, state and health, networks and IPs, published ports, mounts, restart policy, and Compose stack details (project, service, folder, compose files). It **never** sends environment variables or container commands, and secret-looking label values are redacted. Set `SERVCHART_HIDE_PATHS=1` to also drop host paths and stack folders.

All options are in the [main README](https://github.com/opticodev/servchart#agent).
