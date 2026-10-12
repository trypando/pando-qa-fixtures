# Pando benchmark corpus

The cases Pando's benchmark (`test/benchmark` in
[trypando/pando](https://github.com/trypando/pando), issue #90) deploys to
measure its success rate at scale. The benchmark runs these together with the
deploy QA cases in `../cases/`.

| File | Source |
|---|---|
| `cases/frameworks-js.json` | Official examples, starters and templates for JavaScript and TypeScript frameworks |
| `cases/frameworks-dynamic.json` | The same for Python, Ruby, PHP and other interpreted languages |
| `cases/frameworks-compiled.json` | The same for Go, Rust, Java, Kotlin, .NET, Elixir and other compiled languages |
| `cases/platform-samples.json` | Sample apps published by hosting platforms (Render, Railway, Fly.io, DigitalOcean, Heroku, Koyeb, Google Cloud, Azure) |
| `cases/compose-selfhosted.json` | `docker/awesome-compose` and self-hosted apps from awesome-selfhosted |
| `cases/images.json` | Published images: official images, linuxserver.io and other images that serve HTTP |
| `cases/negative.json` | Repositories and images Pando should refuse: libraries, CLIs, desktop and mobile apps, documentation |

`apps/<id>/` holds examples copied out of repositories too large to clone, with
the original license. `tools/validate.py` checks every case file.

## Case format

Every case is one object in a case file's array.

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique across this directory and `../cases/`. Lowercase, digits and `-`, at most 48 characters, prefixed `bm-`. |
| `kind` | yes | `git`, `image` or `upload`. |
| `url`, `ref`, `commit`, `subdir` | `git` | The repository, the branch the commit was taken from, the full 40-character commit, and the directory the app lives in (`""` for the root). The benchmark deploys the commit, so a result does not move when upstream does. |
| `size_kb` | `git` | The repository's size as GitHub reports it. At most 150000: a pinned commit is a full clone. |
| `image` | `image` | A reference with a tag. Never `latest` when the image publishes versioned tags. |
| `path`, `origin` | `upload` | `benchmark/apps/<id>`, and where it was copied from: `{"url", "commit", "subdir", "license"}`. |
| `source` | yes | `framework-example`, `framework-template`, `platform-sample`, `awesome-compose`, `awesome-selfhosted`, `popular-github`, `official-image`, `linuxserver-image`, `published-image`. |
| `framework` | yes | The framework or server, such as `nextjs`, `django`, `spring-boot`, `nginx`; `none` when there is none. |
| `language` | yes | The app's main language, lowercase: `javascript`, `typescript`, `python`, `go`, `java`, `csharp`, `html`, and so on. |
| `packaging` | yes | `static`, `static-generator`, `buildpack` (source with no Dockerfile or compose file), `dockerfile`, `compose`, `image`; for a refusal, `library`, `cli`, `desktop`, `mobile`, `docs` or `empty`. |
| `expect` | yes | `web` when a correct deploy serves HTTP, `refuse` when Pando should decline it. |
| `http_path` | yes | The path to request once deployed, usually `/`. |
| `expect_text` | yes | Text the page at `http_path` always contains, or `null` when only a 2xx–4xx answer can be checked. |
| `facts` | yes | The answers the app's author would give to Pando's questions. See below. |
| `notes` | no | Anything a person reading a failure needs: why a fact was chosen, a known quirk. |

### Facts

Only what the repository itself establishes, read from its code, its
Dockerfile, its compose file or its README. A fact nobody could know from the
repository is left out.

| Fact | Meaning |
|---|---|
| `port` | The port the app serves HTTP on inside its container. |
| `start_command` | The command that starts the server, when the app has no Dockerfile. |
| `build_command` | The command that builds it, when it has one. |
| `static_source` | For a static site: the directory to serve, or `run-build` when a build produces it. |
| `primary_service` | For a compose app: the service that serves the web interface. |
| `dockerfile_path` | When the Dockerfile is not `./Dockerfile`. |
| `deployable_project` | In a repository holding several apps, the one this case is. |
| `build_args` | `{name: value}` for build arguments without a usable default. |
| `slots` | `{NAME: value}` for environment variables the app refuses to start without (a session secret, an admin password). Databases are left to Pando to provision. |
| `answers` | `{question key: answer}` for any other question the author could answer. |

## Choosing cases

- The app must work the normal way for its ecosystem at the pinned commit:
  `docker compose up`, `docker build` and `docker run`, or the framework's own
  start command. A fixture that does not work on its own measures nothing about
  Pando.
- No app that needs a third-party account or API key to serve its first page.
- No repository over 150 MB. Copy the example into `apps/<id>/` instead, with
  its license, when it is worth having.
- One case per app. A repository with several apps can supply several cases,
  each with its own `subdir`.
- Spread cases across frameworks; no framework above about 8% of the corpus.

Run `python3 benchmark/tools/validate.py` before committing.
