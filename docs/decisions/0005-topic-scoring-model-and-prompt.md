---
id: "0005"
title: Songs are scored on topics only, with one fixed model and prompt
status: accepted
date: 2026-11-12
supersedes: null
---

# Songs are scored on topics only, with one fixed model and prompt

## Context

A language model scores each song on a fixed list of 38 topics. Scores from different times are comparable only if the model, its settings and the prompt stay the same. Earlier scoring also asked for a list of values in the same request.

## Decision

The project scores topics only. Values are no longer scored or analyzed.

The model is OpenAI `gpt-5.6-luna` with reasoning effort `medium`. New songs use the topics-only prompt. The model settings live in one file, `prompts/scoring/model.toml`, and the prompt lives next to it as files. Scoring code reads both and refuses a response from any other model. A test pins the hash of the prompt.

Each score keeps a record of the model, the reasoning effort and the prompt hash that produced it.

The prompts and topic definitions are public. They hold no lyric text.

A change of model, settings or prompt needs a new decision, because it makes new scores different from old ones.

## Consequences

- Anyone can see how a song was scored and with what.
- Scores made earlier with the combined topics-and-values prompt stay in the data. The agreement between the two prompts was not measured; an analysis that mixes them carries that risk until a check is made.
- The scoring files arrive in `prompts/scoring/` with the scoring code. Until then `prompts/scoring/README.md` describes them.
