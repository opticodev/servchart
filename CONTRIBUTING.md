# Contributing to ServChart

Thanks for your interest! ServChart is a small project and every bug report, doc fix and pull request helps. This page explains how to get set up, what we're looking for, and the few rules that keep ServChart safe to install.

## Ways to help

- **Try it and tell us what broke.** Especially on setups we can't test ourselves: Synology, Unraid, TrueNAS, Raspberry Pi/ARM, Podman, rootless Docker, unusual reverse proxies or identity providers.
- **Report a map that looks wrong** (missing lines, wrong stack, a host that doesn't match). Use the "Map looks wrong" issue form.
- **Pick an issue** labelled [`good first issue`](https://github.com/opticodev/servchart/labels/good%20first%20issue) or [`help wanted`](https://github.com/opticodev/servchart/labels/help%20wanted). Comment that you're taking it so nobody duplicates work.
- **Improve the docs:** install guides for your platform, screenshots, translations.

**Before a big change** (a new feature, a new dependency, a change to what the agent collects), open an issue or a discussion first. A five-minute conversation can save you a weekend on a pull request we can't merge.

## Project layout

| Folder | What | Stack |
|---|---|---|
| `agent/` | Runs on each host, reads Docker (read-only) and the kernel, pushes a snapshot to the hub | Python 3.9+, **standard library only** |
| `hub/` | Receives reports, stores them, serves the API, reports and checks | Django 5 + Django REST Framework |
| `web/` | The map and Settings UI | React 19, React Flow, Vite |
| `examples/` | Fictional demo data (`make_sample_data.py`) | |
| `docker/`, `Dockerfile` | Hub image | |

## Development setup

```bash
git clone https://github.com/opticodev/servchart.git && cd servchart

# hub (http://localhost:8000)
cd hub && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export SERVCHART_DEBUG=1 PYTHONPATH=../agent
python manage.py migrate && python manage.py createsuperuser
python manage.py load_demo     # fictional hosts, no Docker needed
python manage.py runserver

# web, hot reload, proxies /api to :8000 (second terminal)
cd web && npm install && npm run dev

# agent against your local Docker, prints the snapshot without sending it
cd agent && python -m servchart_agent --stdout
```

## Tests

Every pull request runs these in CI; please run them before pushing:

```bash
cd agent && python -m unittest discover -s tests
cd hub && PYTHONPATH=../agent python manage.py makemigrations --check --dry-run && PYTHONPATH=../agent python manage.py test inventory
cd web && npm run build
```

Add tests with your change: a bug fix comes with a test that fails without it.

## Rules that keep ServChart safe

ServChart runs with access to the Docker socket on people's servers, so a few things are non-negotiable:

1. **The agent only reads.** It issues `GET` requests to the Docker API, never anything that changes state.
2. **Privacy first.** The agent never reads environment variables or container commands. Anything new it collects must be added to the whitelist in `hub/inventory/validation.py` too (the hub re-checks every report), documented in the README's "Privacy & security" section, and must be something a careful admin would be comfortable sending.
3. **No new dependencies in the agent.** Standard library only, so it can run anywhere with plain Python. Hub dependencies need a good reason.
4. **Outbound only.** Hosts never open ports for ServChart; the agent connects out to the hub.
5. **Protocol compatibility.** Reports carry a `schema` number. Breaking changes bump it, and the hub keeps accepting the previous schema for at least one release. Older agents must keep working with a newer hub.
6. **Provider-neutral.** No hard-coded vendors (identity providers, registries, backup tools). Vendor-specific recipes go in the docs.

Changes touching authentication, the agent, log viewing or anything the hub sends over the network get an extra careful review. Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Pull requests

- Keep them focused: one fix or feature per PR.
- Describe what changed and how you tested it; screenshots for UI changes.
- Update `CHANGELOG.md` under an "Unreleased" heading and the README if behaviour or settings change.
- Sign off your commits (`git commit -s`). This adds a `Signed-off-by` line certifying the [Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change or have the right to submit it under the project's license.
- A maintainer reviews within a few days. It's fine to ping if you hear nothing for a week.

## Scope

ServChart is a **map and audit** of Docker infrastructure: what runs where, how it connects, and whether it's healthy, backed up and up to date. It is not a container manager (start/stop/deploy) or a full metrics system; tools like Portainer, Dockhand or Prometheus do those well. Ideas that move it in those directions will usually be declined, kindly.

## Code style

- Python: formatted like the surrounding code, lint-clean with `ruff check --select F,E9` (line length is relaxed).
- JavaScript: Prettier-style formatting (2 spaces, double quotes).
- User-facing text: short, plain sentences; say what to do, not just what went wrong.

## License

ServChart is MIT-licensed. By contributing, you agree that your contributions are licensed under the MIT License. Everyone taking part is expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
