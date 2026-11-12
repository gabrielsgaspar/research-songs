# Scoring prompts

What a language model receives when it scores a song on topics, and with which model ([decision 0005](../../docs/decisions/0005-topic-scoring-model-and-prompt.md)).

The files arrive with the scoring code. This page says what they are, so the structure is fixed before the code moves.

| File | What it holds |
| --- | --- |
| `model.toml` | The one model configuration: provider, model, reasoning effort, batch or direct calls, time limit and retries |
| `topics/` | The topics-only prompt: instruction text, template, answer format, and the topic definitions it uses |

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
- The files are compared by hash, byte for byte. Keep LF line endings. A test pins each hash.
- Each score records the model, the reasoning effort and the prompt hash that produced it. Scoring code skips a song that already has a score from the same model and prompt.
- No lyric text in this folder: no examples taken from songs.
- Tests never call the model.
