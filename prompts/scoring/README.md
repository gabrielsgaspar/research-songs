# Scoring prompts

What a language model receives when it scores a song on topics, and with which model ([decision 0005](../../docs/decisions/0005-topic-scoring-model-and-prompt.md)).

Code reads these files through `songs.stage_30_topics.scoring_prompt.load_scoring_prompt`. That function refuses to load when a file differs from the one that scored the stored songs.

| File | What it holds |
| --- | --- |
| `model.toml` | The one model configuration: provider, model, reasoning effort, batch or direct calls, time limit and retries |
| `topics/instructions.txt` | The rules the model follows when it scores |
| `topics/definitions.json` | One definition per topic, and the definition of `text_kind`. The topic label comes from `topic_ids` |
| `topics/template.jinja2` | The frame that puts definitions, rules and one song into one prompt |

The answer format is built in code from the topic ids: a song is lyrics with 38 scores, or it is not lyrics and every topic is `unknown`.

The code that sends requests and stores scores is not in this repository yet.

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
- The model, the reasoning effort, the three prompt files, the topic labels and the answer format make one hash. It must equal the hash that every stored topics-only score records. A test checks it.
- Each score records the model, the reasoning effort and the prompt hash that produced it. Scoring code skips a song that already has a score from the same model and prompt.
- No lyric text in this folder: no examples taken from songs.
- Tests never call the model.
