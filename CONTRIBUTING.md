# Contributing to ServChart

Thanks for helping! Issues and pull requests are welcome.

- **Bugs / ideas:** open an issue. For bugs, include your Docker version and, if possible, the output of `python -m servchart_agent --stdout` with anything sensitive removed.
- **Code:** fork, create a branch, keep pull requests focused, and add tests:
  - agent: `cd agent && python -m unittest discover -s tests`
  - hub: `cd hub && python manage.py test inventory`
- **Privacy is a feature:** any change to what the agent collects must keep environment variables out and must be mirrored in `hub/inventory/validation.py`.
- **Agent ↔ hub protocol:** reports carry a `schema` number. Breaking changes bump it, and the hub keeps accepting the previous version for at least one release.

By contributing you agree that your contributions are licensed under the MIT License.
