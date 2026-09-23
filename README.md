# Pando deploy QA sources

Everything Pando's deploy QA (`test/deploy-qa` in
[bemeek-io/pando](https://github.com/bemeek-io/pando)) deploys: 169 cases in
three sets.

| File | Cases | What |
|---|---|---|
| `cases/generated.json` | 66 | Apps in `apps/`, written for the test: static sites; Node/Deno/Bun, Python, Go, Java, Rust, Ruby, PHP, .NET and Elixir projects with no build files; Dockerfile variants; compose topologies; repositories Pando should refuse to deploy (a library, a CLI, a README) |
| `cases/public-repos.json` | 79 | Public GitHub repositories: official samples, getting-started repos, `docker/awesome-compose`, self-hosted apps |
| `cases/images.json` | 24 | Published Docker images |

Each case says how the app is packaged, what a correct deploy looks like, and
the answers its author would give to Pando's questions (`facts`). A public
repository is pinned to a branch, not a commit, so upstream changes can move its
result; note that when comparing runs.

- `apps/<id>/` — one generated app per directory. Every page it serves contains
  `PANDO-QA <id> OK`, so the test can tell the right app answered.
- `src/prebuilt-binary/` — source for `apps/edge-prebuilt-binary/server`, which
  `qa.py up` compiles for the Docker host's architecture. The binary is not
  committed.

Pando's `qa.py` clones this repository at a pinned commit, so changing a fixture
means committing here and updating the pin in Pando.

When adding an app, check it runs the normal way for its ecosystem first: a
fixture that does not work on its own measures nothing about Pando.
