---
id: "0011"
title: Combined-prompt topic scores count as scored
status: accepted
date: 2026-11-25
supersedes: null
---

# Combined-prompt topic scores count as scored

## Context

Decision 0005 keeps the topic scores of the old combined topics-and-values prompt, but nobody had measured how well they agree with the topics-only prompt. After the score import of 2026-11-24, 2,304,011 eligible songs have only a combined-prompt score, and 1,379,176 have a topics-only score (`docs/status/scoring.md`). `songs score prepare` treats the combined-prompt songs as unscored, so it would pay to score them again.

`songs score agreement` measures the agreement at no cost. It uses songs of one country with the same lyric text and decade, where one song has a topics-only score and the other a combined-prompt score. Both songs got the same request. `docs/status/prompt_agreement.md` gives the result:

- 8,629 pairs.
- The same `text_kind` in 99.9% of the pairs.
- Pearson correlation per topic from 0.844 to 0.975.
- The topics-only prompt scores lower on most topics. The mean difference per topic is from -4.91 to +0.41 points, on a scale from 0 to 100.

The pairs are songs with copied text, not a random sample. No free test-retest baseline exists, because the old pipeline copied one response to songs with the same text.

## Decision

1. A topic score from the combined prompt (`8a51ce6792177109997b9720f2e18fca1ccdcca553cf7cc46ec1f830d172dc51`, `gpt-5.6-luna`) counts as scored. `songs score prepare` does not score it again, and `songs score status` counts it as scored. Each score keeps its own prompt hash.
2. Analyses use combined-prompt and topics-only scores together. They do not report the count of songs of each prompt.
3. When `songs score agreement` shows a topic with a Pearson correlation below 0.80 or a mean difference above 5 points, this decision is reviewed for that topic.

## Consequences

- No money is spent to score 2.3 million songs again. Scoring runs go to the 1.1 million songs with no score.
- `songs.stage_30_topics.scoring_run.ACCEPTED_PROMPTS` names the combined prompt. A test checks that its scores count as scored.
- A country-year mean mixes two prompts. The topics-only prompt scores up to 5 points lower on some topics, so a small level shift can remain where the mix of prompts changes over time.
