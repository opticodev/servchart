# Security policy

ServChart sees a lot about your infrastructure, so we take reports seriously.

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private vulnerability reporting ("Security" tab → "Report a vulnerability") on this repository. You'll get an answer within 7 days.

## Design rules we hold ourselves to

- The agent only issues `GET` requests to the Docker API.
- Container environment variables and command lines are never read into a report.
- The hub re-validates every report against a whitelist, so a modified agent can't store more than the UI shows.
- Host tokens are stored only as SHA-256 hashes, are per host, and can be disabled or rotated.
- Agent tokens can only submit reports. They can't read the map or any other host's data.

## Known limitation

Mounting `/var/run/docker.sock` into a container gives that container control over Docker, even with `:ro`. The README shows how to run the agent behind a read-only socket proxy.
