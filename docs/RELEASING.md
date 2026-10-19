# Releasing ServChart

A release publishes three things from one git tag:

| What | Where | Who installs it |
|---|---|---|
| Hub image | Docker Hub `opticodev/servchart-hub` (mirror: `ghcr.io/opticodev/servchart-hub`) | everyone (`docker compose up`) |
| Agent image | Docker Hub `opticodev/servchart-agent` (mirror: `ghcr.io/opticodev/servchart-agent`) | most agent users |
| Agent package | PyPI: `servchart-agent` | people running the agent without Docker (`pipx install servchart-agent`) |

The hub is **not** published to PyPI. It's a web app with a built React UI, so the Docker image is how people run it.

## One-time setup

### 1. Docker Hub (main image registry)

1. Create the repositories `opticodev/servchart-hub` and `opticodev/servchart-agent` (public).
2. Create an access token: Docker Hub → **Account settings → Personal access tokens**, scope **Read & Write**.
3. In GitHub → **Settings → Secrets and variables → Actions**, add `DOCKERHUB_USERNAME` (your Docker Hub user) and `DOCKERHUB_TOKEN` (the token).
4. Paste the repository descriptions (short description + overview) on each Docker Hub repo page.

### 2. GHCR (mirror)

Nothing to configure: the workflow logs in with the built-in `GITHUB_TOKEN`. After the **first** release, make the two packages public:
GitHub → your profile/org → **Packages** → `servchart-hub` → **Package settings** → **Change visibility → Public**. Repeat for `servchart-agent`. While you're there, use **Connect repository** to link each one to `opticodev/servchart`.

### 3. PyPI (trusted publishing, no API token)

1. Create an account on <https://pypi.org> and turn on two-factor authentication (required).
2. Check the name is free: <https://pypi.org/project/servchart-agent/> should show "Not Found".
3. Go to <https://pypi.org/manage/account/publishing/> → **Add a new pending publisher**:
   - PyPI project name: `servchart-agent`
   - Owner: `opticodev`
   - Repository name: `servchart`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
4. In the GitHub repo: **Settings → Environments → New environment** named `pypi`. Optionally add yourself as a required reviewer so each PyPI upload waits for your click.

Optional dry run: repeat step 3 on <https://test.pypi.org> and temporarily add `repository-url: https://test.pypi.org/legacy/` to the publish step.

## Every release

1. Update the version in **both** files (the workflow refuses mismatches):
   - `agent/servchart_agent/__init__.py`
   - `hub/servchart/__init__.py`
2. Commit, then tag and push:
   ```bash
   git commit -am "Release 0.2.0"
   git tag v0.2.0
   git push origin main v0.2.0
   ```
3. Watch **Actions → Release**. When it's green:
   - `docker pull opticodev/servchart-hub:0.2.0` (and `ghcr.io/opticodev/servchart-hub:0.2.0`)
   - `pipx install servchart-agent==0.2.0`
4. Create a GitHub Release from the tag with short notes (**Releases → Draft a new release**).

PyPI never lets you re-upload a version number. If something goes wrong after the upload, fix it and release `0.2.1`.
