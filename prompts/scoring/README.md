# Scoring prompts

What a language model receives when it scores a song on topics, and with which model ([decision 0005](../../docs/decisions/0005-topic-scoring-model-and-prompt.md)).

Code reads these files through `songs.stage_30_topics.scoring_prompt.load_scoring_prompt`. That function refuses to load when a file differs from the one that scored the stored songs.

| File | What it holds |
| --- | --- |
| `model.toml` | The one model configuration: provider, model, reasoning effort, batch or direct calls, time limit and retries |
| `topics/instructions.txt` | The rules the model follows when it scores |
| `topics/text_kind.txt` | The definition of `text_kind`, the field that says whether a text is song lyrics |
| `topics/template.jinja2` | The frame that puts definitions, rules and one song into one prompt |

Topic labels and definitions are not in this folder. They are in [`resources/topics.toml`](../../resources/topics.toml), and the prompt takes them from there. To change a label or a definition, edit only that file; to change the wording of the prompt, edit only the files here. Either change needs a new decision and a new pinned hash.

The answer format is built in code from the topic ids: a song is lyrics with 38 scores, or it is not lyrics and every topic is `unknown`.

`songs.stage_30_topics.scoring_run` sends the requests and stores the scores (`songs score prepare`, `submit` and `collect`). `songs score status` shows how many eligible songs of each country have a current score; `uv run songs score status --write` writes [`docs/status/scoring.md`](../../docs/status/scoring.md). The data layout standard describes the run. `uv run songs score agreement --write` writes [`docs/status/prompt_agreement.md`](../../docs/status/prompt_agreement.md): for songs of one country with the same text and decade, it compares the scores of the current prompt with the scores of each other prompt. These pairs cost nothing, because both songs got the same request.

## How to score a country

Run these steps on one computer, in order, for one country or for one decade of a country. An agent can do every step except step 5. Step 5 costs money, so only a person does it.

1. Get the newest songs and scores of the country from the bucket: `uv run songs data pull <ISO3> --no-catalog`.
2. Read the state of the scores: `uv run songs score status <ISO3>`. A large `other_prompt` count before the first scoring run often means that the old scores are not imported. Then import them first, and do not pay for them again: `uv run songs lyrics import-scores <ISO3>`. That command reads the old data folder from `SONGS_OLD_DATA_ROOT`.
3. Write the batch file: `uv run songs score prepare <ISO3> --max-requests 1000`. Add `--decade 1980s` to take one decade only. The command copies, at no cost, the scores of songs with the same text and decade. It prints the counts, the run id and the cost estimate in US dollars. It sends nothing.
4. Read the counts. `requests` is what the run sends, `reused` is what it copied, and `left_for_next_run` and `other_decade` wait for a later run. If the estimate is too high, prepare again with a lower `--max-requests`.
5. A person starts the batch with a cost limit: `uv run songs score submit <run id> --max-usd 20`. The command asks the person to type the run id.
6. Collect the answers: `uv run songs score collect <run id>`. While the batch runs, the command prints its state and writes nothing. Run it again later. A batch ends in 24 hours or less.
7. Build the analysis release from the new scores: `uv run songs analysis release`. The country-year panel (`songs panel countries`) does not read scores, so it does not change.
8. Upload the new folders: `uv run songs data sync`, read the report, then `uv run songs data sync --write`.
9. Write the status page, `uv run songs score status --write`, and commit `docs/status/scoring.md` in a pull request.

Repeat steps 3 to 6 until `requests` is 0. Songs with no valid answer are taken again by the next `prepare`.

## The fixed values

| Setting | Value |
| --- | --- |
| Provider | OpenAI |
| Model | `gpt-5.6-luna` |
| Reasoning effort | `medium` |
| What is scored | 38 topics, each from 0 to 100; no values |
| Answer format | Strict JSON with a fixed field order |

Topic ids, labels and families are in [`docs/standards/topics.md`](../../docs/standards/topics.md). Families are used in analysis only; the prompt does not name them.

## Rules

- Do not change a file here without a new decision. A changed prompt or model makes new scores different from old ones.
- The model, the reasoning effort, the three prompt files, the topic labels and definitions, and the answer format make one hash. It must equal the hash that every stored topics-only score records. A test checks it.
- Each score records the model, the reasoning effort and the prompt hash that produced it. Scoring code skips a song that already has a score from the same model and prompt, or from the old combined topics-and-values prompt that [decision 0011](../../docs/decisions/0011-combined-prompt-scores.md) accepts (`scoring_run.ACCEPTED_PROMPTS`). It also copies, at no cost, the score of another song of the same country with the same lyric text and decade, because that song would get the same request.
- No lyric text in this folder: no examples taken from songs.
- Tests never call the model.
