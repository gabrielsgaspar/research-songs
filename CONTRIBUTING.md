# Contributing

This guide is for everyone who changes this repository. Gabriel reviews and merges every pull request.

## Set up once

Follow [Setup in the README](README.md#setup). Then check that the tests pass:

```bash
uv run pytest
```

## Find your way

1. Read [`README.md`](README.md) for the project map.
2. Read [`AGENTS.md`](AGENTS.md) for the rules. They apply to people too.
3. Read [`docs/decisions/README.md`](docs/decisions/README.md) when you want to know why a rule exists.
4. Read [`docs/standards/data_layout.md`](docs/standards/data_layout.md) before you write code that reads or writes data. It says where each data file goes and which columns each table has.

## Make a change

1. Open an issue from a template, or pick an open one. Say in the issue that you are working on it.
2. Start a branch from an up-to-date `main`:

   ```bash
   git switch main
   git pull
   git switch -c <your-github-username>/<short-name>
   ```

3. Make small commits. Each message says what changed.
4. Run the checks:

   ```bash
   uv run ruff check .
   uv run ruff format .
   uv run pytest
   ```

5. Push the branch and open a pull request into `main`. Fill in the template. Keep the pull request to one task.
6. Gabriel reviews it. Push more commits to the same branch when he asks for changes. Do not force-push.
7. Delete the branch after the merge.

## Never commit

- Data files, or anything under `data/`, `outputs/`, `reports/`, `scratch/` or `overleaf/`.
- Lyric text, in any file. A fixture that needs song text uses invented text.
- `.env`, credentials, tokens or key files.
- Email addresses or other personal details.
- Identifiers of private resources, such as bucket names or spreadsheet ids.

This repository is public. Something that was pushed once can be copied by anyone, even after it is deleted. When you are not sure, leave it out and ask.

## Add a dependency

Open a pull request that only adds the package:

```bash
uv add <package>
```

## Ask for help

Open an issue, or write to Gabriel on the channel you already use with him.
