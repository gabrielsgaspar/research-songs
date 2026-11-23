"""Score songs on topics with the Batch API and the prompt of `prompts/scoring/`.

A scoring run has three steps. Each one is a command of `songs score`.

    prepare  For each country, read the newest songs folder and the newest scores
             folder. Take the eligible songs that have no score from this prompt and
             model for their current lyric text, and write one batch file. Songs with
             the same lyric text and decade share one request. Nothing is sent.
    submit   Upload the batch file and start the batch, below a cost limit in US
             dollars. Only a person runs this step: it costs money.
    collect  Read the answers and write lyrics/<ISO3>/scores/<run id>/ for each
             country: every score of the newest scores folder, with the new scores
             added or put in place of the old score of the same song.

The working files of a run are in `staging/scoring/<run id>/` of the data folder:
the batch file (with lyric text), the request of each song, the plan, and the batch
ids. That folder is not a version folder and never goes to the bucket. A song in a
run that is not collected yet is not prepared again.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

import duckdb
import pandas as pd

from songs.common import manifests, paths, run_records, schemas
from songs.stage_30_topics.scoring_prompt import FIELD_ORDER, ScoringPrompt, load_scoring_prompt
from songs.stage_30_topics.topic_ids import TOPIC_IDS
from songs.stage_50_analysis import eligible_songs

API_KEY_ENV = "OPENAI_API_KEY"
MAX_REQUESTS = 50_000
MAX_BATCH_BYTES = 190 * 1024 * 1024
OUTPUT_TOKENS_PER_REQUEST = 1_000
USD_PER_MILLION_INPUT_TOKENS = 0.20
USD_PER_MILLION_OUTPUT_TOKENS = 1.20
BATCH_PRICE_FACTOR = 0.5
DONE_STATES = ("completed", "expired", "cancelled", "failed")
TEXT_KINDS = ("song_lyrics", "non_song", "uncertain")
FAILURES = ("no_answer", "request_error", "http_error", "not_completed", "bad_answer")

REQUESTS_FILE = "requests.jsonl"
ASSIGNMENTS_FILE = "assignments.jsonl"
PLAN_FILE = "plan.json"
STARTED_FILE = "submit_started.json"
BATCH_FILE = "batch.json"
COLLECTED_FILE = "collected.json"


class BatchClient(Protocol):
    """The four calls of the Batch API that a scoring run makes."""

    def upload(self, path: Path) -> str: ...
    def create_batch(self, file_id: str, endpoint: str, metadata: dict[str, str]) -> str: ...
    def batch(self, batch_id: str) -> dict[str, Any]: ...
    def file_content(self, file_id: str) -> bytes: ...


class OpenAIBatches:
    """The Batch API of OpenAI over HTTPS, with the time limit and retries of `model.toml`."""

    def __init__(self, settings: dict[str, Any], api_key: str | None = None) -> None:
        self.base = settings["api_base_url"].rstrip("/")
        self.timeout = float(settings["timeout_seconds"])
        self.retries = int(settings["max_retries"])
        self.key = api_key or os.environ.get(API_KEY_ENV, "")
        if not self.key:
            raise RuntimeError(f"{API_KEY_ENV} is not set")

    def _call(self, method: str, path: str, body: bytes | None = None, kind: str = "") -> bytes:
        headers = {"Authorization": f"Bearer {self.key}"}
        if kind:
            headers["Content-Type"] = kind
        request = urllib.request.Request(self.base + path, body, headers, method=method)
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code < 500 and error.code != 429 or attempt == self.retries:
                    raise RuntimeError(f"{method} {path}: HTTP {error.code}") from error
            except urllib.error.URLError:
                if attempt == self.retries:
                    raise
            time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def upload(self, path: Path) -> str:
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nbatch\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{path.name}"\r\nContent-Type: application/jsonl\r\n\r\n'
            ).encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        kind = f"multipart/form-data; boundary={boundary}"
        return json.loads(self._call("POST", "/files", body, kind))["id"]

    def create_batch(self, file_id: str, endpoint: str, metadata: dict[str, str]) -> str:
        body = {
            "input_file_id": file_id,
            "endpoint": endpoint,
            "completion_window": "24h",
            "metadata": metadata,
        }
        return json.loads(
            self._call("POST", "/batches", json.dumps(body).encode(), "application/json")
        )["id"]

    def batch(self, batch_id: str) -> dict[str, Any]:
        return json.loads(self._call("GET", f"/batches/{batch_id}"))

    def file_content(self, file_id: str) -> bytes:
        return self._call("GET", f"/files/{file_id}/content")


def run_dir(data: Path, run_id: str) -> Path:
    return data / "staging" / "scoring" / paths.check_run_id(run_id)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def read_plan(data: Path, run_id: str) -> dict[str, Any]:
    """The plan that `prepare` wrote for a run."""
    return _read_json(run_dir(data, run_id) / PLAN_FILE)


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _open_runs(data: Path) -> list[Path]:
    """The runs that are prepared and not collected."""
    folder = data / "staging" / "scoring"
    if not folder.is_dir():
        return []
    return sorted(
        run
        for run in folder.iterdir()
        if (run / PLAN_FILE).is_file() and not (run / COLLECTED_FILE).exists()
    )


def _reserved(data: Path) -> set[tuple[str, str, str]]:
    """(country, song id, lyrics hash) of each song in a run that is not collected."""
    return {
        (item["country_iso3"], song_id, item["lyrics_sha256"])
        for run in _open_runs(data)
        for item in _read_lines(run / ASSIGNMENTS_FILE)
        for song_id in item["song_ids"]
    }


def _scored(connection: duckdb.DuckDBPyConnection, folder: Path | None, prompt: ScoringPrompt):
    """(song id, lyrics hash) of each score of `folder` from this prompt and model."""
    if folder is None:
        return set()
    provenance = schemas.read_table(schemas.SCORE_PROVENANCE, folder, connection)
    return set(
        provenance.filter(
            f"prompt_sha256 = '{prompt.sha256}' AND model = '{prompt.settings['model']}'"
        )
        .project("song_id, lyrics_sha256")
        .fetchall()
    )


def _decade(year: Any) -> str | None:
    return None if pd.isna(year) else f"{int(year) // 10 * 10}s"


def _custom_id(iso3: str, lyrics_sha256: str, decade: str | None) -> str:
    key = f"{iso3}|{lyrics_sha256}|{decade or ''}"
    return f"{iso3}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:40]}"


def _estimate(input_bytes: int, requests: int) -> dict[str, float | int]:
    """An upper estimate: about 4 bytes of request per input token, and no cache reads."""
    input_tokens = input_bytes // 4
    output_tokens = requests * OUTPUT_TOKENS_PER_REQUEST
    usd = BATCH_PRICE_FACTOR * (
        input_tokens * USD_PER_MILLION_INPUT_TOKENS + output_tokens * USD_PER_MILLION_OUTPUT_TOKENS
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd": round(usd / 1_000_000, 4),
    }


def prepare(
    data: Path,
    countries: list[str],
    max_requests: int,
    *,
    run_id: str | None = None,
    rule_files: dict[str, Path] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Write the batch file of a new run and return its plan. Nothing is sent.

    `max_requests` stops the run at that many requests; the songs that are left wait
    for the next run. `rule_files` overrides the files of the eligibility rule
    (the keyword arguments of `eligible_songs.load_rule`).
    """
    if not 1 <= max_requests <= MAX_REQUESTS:
        raise ValueError(f"max_requests must be from 1 to {MAX_REQUESTS}")
    prompt = load_scoring_prompt(root)
    run_id = paths.check_run_id(run_id) if run_id else run_records.new_run_id()
    folder = run_dir(data, run_id)
    reserved = _reserved(data)
    connection = duckdb.connect()
    exceptions, lists = eligible_songs.load_rule(connection, data, **(rule_files or {}))
    plan: dict[str, Any] = {
        "run_id": run_id,
        "prompt_sha256": prompt.sha256,
        "model": prompt.settings["model"],
        "countries": {},
    }
    requests: list[bytes] = []
    assignments: list[dict[str, Any]] = []
    for code in dict.fromkeys(paths.check_iso3(code.upper()) for code in countries):
        songs_folder = paths.latest_country_songs_dir(data, code)
        if songs_folder is None:
            raise FileNotFoundError(f"{code} has no complete songs folder")
        scores_folder = paths.latest_country_scores_dir(data, code)
        songs = schemas.read_table(schemas.COUNTRY_SONGS, songs_folder, connection)
        classified = eligible_songs.classify(songs, exceptions, lists)
        eligible = classified.filter("ineligible_reason IS NULL").project(
            "song_id, lyrics, lyrics_sha256, year"
        )
        scored = _scored(connection, scores_folder, prompt)
        groups: dict[str, dict[str, Any]] = {}
        total = songs.aggregate("count(*)").fetchall()[0][0]
        counts = Counter(songs=total, eligible=0, scored=0, in_open_run=0)
        for song_id, lyrics, lyrics_sha256, year in eligible.order("song_id").fetchall():
            counts["eligible"] += 1
            if (song_id, lyrics_sha256) in scored:
                counts["scored"] += 1
                continue
            if (code, song_id, lyrics_sha256) in reserved:
                counts["in_open_run"] += 1
                continue
            decade = _decade(year)
            custom_id = _custom_id(code, lyrics_sha256, decade)
            group = groups.setdefault(
                custom_id, {"lyrics": lyrics, "lyrics_sha256": lyrics_sha256, "decade": decade}
            )
            group.setdefault("song_ids", []).append(song_id)
        counts["requests"] = counts["songs_to_score"] = counts["left_for_next_run"] = 0
        for custom_id, group in sorted(groups.items()):
            if len(requests) >= max_requests:
                counts["left_for_next_run"] += len(group["song_ids"])
                continue
            body = prompt.request_body(prompt.render(code, group["decade"], group["lyrics"]))
            line = {
                "custom_id": custom_id,
                "method": "POST",
                "url": prompt.settings["endpoint"],
                "body": body,
            }
            requests.append((json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
            assignments.append(
                {
                    "custom_id": custom_id,
                    "country_iso3": code,
                    "song_ids": group["song_ids"],
                    "lyrics_sha256": group["lyrics_sha256"],
                    "decade": group["decade"],
                }
            )
            counts["requests"] += 1
            counts["songs_to_score"] += len(group["song_ids"])
        plan["countries"][code] = {
            "songs_folder": paths.data_relative(data, songs_folder),
            "scores_folder": scores_folder and paths.data_relative(data, scores_folder),
            **counts,
        }
    size = sum(len(line) for line in requests)
    if size > MAX_BATCH_BYTES:
        raise ValueError(f"the batch file would have {size} bytes; lower max_requests")
    plan["requests"] = len(requests)
    plan["estimate"] = _estimate(size, len(requests))
    if requests:
        folder.mkdir(parents=True)
        (folder / REQUESTS_FILE).write_bytes(b"".join(requests))
        with (folder / ASSIGNMENTS_FILE).open("x", encoding="utf-8", newline="\n") as handle:
            handle.writelines(json.dumps(item) + "\n" for item in assignments)
        _write_json(folder / PLAN_FILE, plan)
    return plan


def submit(
    data: Path, run_id: str, max_usd: float, client: BatchClient | None = None
) -> dict[str, Any]:
    """Upload the batch file of a prepared run and start the batch.

    Raise ValueError when the estimate is above `max_usd`, when the prompt changed
    since the run was prepared, and when the run was submitted before.
    """
    folder = run_dir(data, run_id)
    plan = read_plan(data, run_id)
    prompt = load_scoring_prompt()
    if plan["prompt_sha256"] != prompt.sha256:
        raise ValueError("the scoring prompt changed after the run was prepared")
    if plan["estimate"]["usd"] > max_usd:
        raise ValueError(
            f"the estimate is {plan['estimate']['usd']} USD, above the limit of {max_usd} USD"
        )
    if (folder / STARTED_FILE).exists():
        raise ValueError(
            f"run {run_id} was submitted before. If {BATCH_FILE} is absent, the start did "
            "not end: look for the batch in the OpenAI dashboard before you prepare again"
        )
    client = client or OpenAIBatches(prompt.settings)
    _write_json(folder / STARTED_FILE, {"started_utc": run_records.utc_now()})
    file_id = client.upload(folder / REQUESTS_FILE)
    batch_id = client.create_batch(
        file_id, prompt.settings["endpoint"], {"project": "songs", "run_id": run_id}
    )
    batch = {"input_file_id": file_id, "batch_id": batch_id, "submitted_utc": run_records.utc_now()}
    _write_json(folder / BATCH_FILE, batch)
    return batch


def read_answer(record: dict[str, Any], model: str) -> tuple[dict[str, Any] | None, str]:
    """Return the scores of one line of the batch output, or None and the reason.

    The scores are `text_kind` and one integer from 0 to 100, or None, for each topic.
    """
    if record.get("error"):
        return None, "request_error"
    response = record.get("response") or {}
    if response.get("status_code") != 200:
        return None, "http_error"
    body = response.get("body") or {}
    if body.get("status") != "completed":
        return None, "not_completed"
    answered = str(body.get("model"))
    if answered != model and not answered.startswith(f"{model}-"):
        return None, "bad_answer"
    texts = [
        part.get("text", "")
        for item in body.get("output") or []
        if item.get("type") == "message"
        for part in item.get("content") or []
        if part.get("type") == "output_text"
    ]
    try:
        song = json.loads("".join(texts))["song"]
    except ValueError, KeyError, TypeError:
        return None, "bad_answer"
    if not isinstance(song, dict) or tuple(song) != FIELD_ORDER:
        return None, "bad_answer"
    kind = song["text_kind"]
    values = [song[topic] for topic in TOPIC_IDS]
    if kind == "song_lyrics" and all(
        isinstance(value, str) and value.isdigit() and int(value) <= 100 for value in values
    ):
        return {"text_kind": kind} | {t: int(v) for t, v in zip(TOPIC_IDS, values, strict=True)}, ""
    if kind in TEXT_KINDS[1:] and all(value == "unknown" for value in values):
        return {"text_kind": kind} | dict.fromkeys(TOPIC_IDS), ""
    return None, "bad_answer"


def _write_country(
    data: Path,
    code: str,
    rows: list[dict[str, Any]],
    plan_country: dict[str, Any],
    prepared: str,
    counts: dict[str, int],
) -> Path:
    """Write the newest scores of a country, with `rows` in place of older scores.

    The folder takes a new run id, so it is the newest scores folder of the country.
    """
    connection = duckdb.connect()
    new = pd.DataFrame(rows)
    keep = ["song_id"]
    previous = paths.latest_country_scores_dir(data, code)
    parts = {}
    for table in (schemas.SCORE_TOPICS, schemas.SCORE_PROVENANCE):
        names = [column.name for column in table.all_columns]
        fresh = schemas.cast_to_schema(table, new[names], connection)
        if previous is not None:
            old = schemas.read_table(table, previous, connection).join(
                fresh.project(", ".join(keep)), "song_id", how="anti"
            )
            fresh = old.union(fresh)
        parts[table.file] = fresh.order("song_id")
    run_id = run_records.new_run_id()
    out = paths.country_scores_dir(data, code, run_id)
    out.mkdir(parents=True, exist_ok=False)
    for table in (schemas.SCORE_TOPICS, schemas.SCORE_PROVENANCE):
        schemas.write_table(table, parts[table.file], out)
    total = parts[schemas.SCORE_TOPICS.file].aggregate("count(*)").fetchall()[0][0]
    counts = {"scores": total, "scores_carried": total - len(rows), **counts}
    inputs = [plan_country["songs_folder"]]
    if previous is not None:
        inputs.append(paths.data_relative(data, previous))
    manifests.write_manifest(
        data,
        out,
        "country_scores",
        country_iso3=code,
        run_id=run_id,
        inputs=inputs,
        counts=counts,
        notes=(
            f"Scoring run {prepared} through the Batch API. The scores of the earlier "
            "scores folder stay, except where this run scored the same song again. "
            "The working files of the run are in staging/scoring/ of the data folder."
        ),
    )
    return out


def collect(data: Path, run_id: str, client: BatchClient | None = None) -> dict[str, Any]:
    """Read the answers of a submitted run and write one scores folder for each country.

    When the batch has not ended, return its state and write nothing. A song with no
    valid answer gets no score; the next prepared run takes it again.
    """
    folder = run_dir(data, run_id)
    if (folder / COLLECTED_FILE).exists():
        raise ValueError(f"run {run_id} is collected")
    plan = _read_json(folder / PLAN_FILE)
    batch_ids = _read_json(folder / BATCH_FILE)
    prompt = load_scoring_prompt()
    client = client or OpenAIBatches(prompt.settings)
    batch = client.batch(batch_ids["batch_id"])
    if batch.get("status") not in DONE_STATES:
        return {"status": batch.get("status"), "written": []}
    records: dict[str, dict[str, Any]] = {}
    for key, name in (("output_file_id", "output.jsonl"), ("error_file_id", "errors.jsonl")):
        if batch.get(key):
            content = client.file_content(batch[key])
            (folder / name).write_bytes(content)
            for line in content.decode("utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    records[record["custom_id"]] = record
    scored_utc = run_records.utc_now()
    by_country: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, Counter] = {}
    for item in _read_lines(folder / ASSIGNMENTS_FILE):
        code = item["country_iso3"]
        tally = counts.setdefault(code, Counter({name: 0 for name in FAILURES}))
        tally["requests"] += 1
        record = records.get(item["custom_id"])
        answer, reason = read_answer(record, plan["model"]) if record else (None, "no_answer")
        if answer is None:
            tally[reason] += 1
            continue
        tally["answers"] += 1
        tally[f"songs_{answer['text_kind']}"] += len(item["song_ids"])
        for song_id in item["song_ids"]:
            by_country.setdefault(code, []).append(
                {
                    "country_iso3": code,
                    "song_id": song_id,
                    "lyrics_sha256": item["lyrics_sha256"],
                    **answer,
                    "prompt_sha256": plan["prompt_sha256"],
                    "model": plan["model"],
                    "status": "complete",
                    "scored_utc": scored_utc,
                }
            )
    written = [
        paths.data_relative(
            data,
            _write_country(data, code, rows, plan["countries"][code], run_id, dict(counts[code])),
        )
        for code, rows in sorted(by_country.items())
    ]
    summary = {
        "status": batch["status"],
        "collected_utc": scored_utc,
        "written": written,
        "counts": {code: dict(tally) for code, tally in counts.items()},
    }
    _write_json(folder / COLLECTED_FILE, summary)
    return summary
