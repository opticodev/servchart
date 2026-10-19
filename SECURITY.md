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
- Single sign-on headers are trusted only from the proxy addresses listed in `SERVCHART_SSO_TRUSTED_PROXIES`, and never on the agent or health endpoints.
- Container logs are off unless a host's agent sets `SERVCHART_ALLOW_LOGS=1`. Only admins can request them. The agent only answers for containers that exist, redacts secret-looking values, and is polled over its own outbound connection. The hub deletes results once read, and every view is recorded in the activity log.
- Uploaded logos and favicons are identified by their bytes. SVGs containing scripts, event handlers or embedded documents are rejected, and images are served with `nosniff` and a sandboxing Content-Security-Policy.
- CSV exports prefix cells starting with `=`, `+`, `-` or `@` to prevent spreadsheet formula injection.
- OpenID Connect uses the authorization code flow with PKCE, state and nonce. ID tokens are fetched server to server over verified HTTPS, and checked for issuer, audience and expiry.

## Known limitation

Mounting `/var/run/docker.sock` into a container gives that container control over Docker, even with `:ro`. The README shows how to run the agent behind a read-only socket proxy.
