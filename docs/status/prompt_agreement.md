# Agreement of the scoring prompts

Generated from the data folder by `uv run songs score agreement --write`. Do not edit by hand.

The current prompt has the hash `c51d257f2d6b` and the model is `gpt-5.6-luna`. A pair is two songs of one country with the same lyric text and decade: one has a score from the current prompt and model, the other a score from another prompt or model. Both got the same request. Differences are the current score minus the other score, in points from 0 to 100.

- Scores read: 3763439
- Scores left out because the song has other text now: 37879
- Texts (country, text, decade) with a current score: 1364510
- Texts (country, text, decade) with another score: 2172521

## Prompt `8a51ce679217`, model `gpt-5.6-luna`

Pairs: 8629. Same `text_kind`: 99.9% of the pairs.

| Topic | Label | Pairs | Pearson | Mean difference | Mean absolute difference |
| --- | --- | --- | --- | --- | --- |
| T01 | Romantic love & devotion | 8604 | 0.951 | -1.82 | 5.00 |
| T02 | Romantic longing & separation | 8604 | 0.924 | -1.24 | 4.33 |
| T03 | Heartbreak & separation | 8604 | 0.961 | -1.81 | 3.90 |
| T04 | Unrequited & hidden love | 8604 | 0.867 | -1.71 | 3.40 |
| T05 | Desire & casual relationships | 8604 | 0.948 | -2.22 | 4.16 |
| T06 | Betrayal, conflict & dysfunction | 8604 | 0.907 | -2.00 | 5.43 |
| T07 | Nostalgia & memory | 8604 | 0.920 | -1.02 | 4.21 |
| T08 | Loneliness & isolation | 8604 | 0.899 | -4.91 | 7.87 |
| T09 | Personal struggle & emotional pain | 8604 | 0.886 | -3.82 | 8.52 |
| T10 | Existential reflection & uncertainty | 8604 | 0.904 | -2.59 | 5.48 |
| T11 | Death & mortality | 8604 | 0.933 | -1.64 | 4.45 |
| T12 | Grief & mourning | 8604 | 0.921 | -0.36 | 1.39 |
| T13 | Religious faith & spirituality | 8604 | 0.945 | -0.40 | 2.29 |
| T14 | Resilience & hope | 8604 | 0.901 | -1.30 | 6.44 |
| T15 | Personal identity & self-discovery | 8604 | 0.871 | -2.32 | 5.51 |
| T16 | Personal freedom & empowerment | 8604 | 0.887 | -2.33 | 6.24 |
| T17 | Ambition, dreams & aspiration | 8604 | 0.914 | -0.61 | 3.65 |
| T18 | Self-confidence & bravado | 8604 | 0.950 | -0.20 | 4.13 |
| T19 | Artistic expression & creativity | 8604 | 0.952 | -1.21 | 3.18 |
| T20 | Rebellion & defiance | 8604 | 0.875 | -0.24 | 3.84 |
| T21 | Social injustice & inequality | 8604 | 0.933 | -0.43 | 2.26 |
| T22 | Political dissent & resistance | 8604 | 0.937 | -0.16 | 1.23 |
| T23 | Social criticism & corruption | 8604 | 0.940 | +0.14 | 3.03 |
| T24 | War, violence & conflict | 8604 | 0.960 | -1.80 | 3.93 |
| T25 | Poverty & hardship | 8604 | 0.942 | -0.41 | 2.16 |
| T26 | Urban street life & crime | 8604 | 0.975 | -0.38 | 2.28 |
| T27 | Wealth, status & fame | 8604 | 0.963 | -0.77 | 2.94 |
| T28 | Family bonds | 8604 | 0.936 | -0.41 | 1.93 |
| T29 | Friendship & companionship | 8604 | 0.903 | -0.37 | 2.76 |
| T30 | Community, peace & solidarity | 8604 | 0.889 | -0.28 | 3.41 |
| T31 | Cultural & national identity | 8604 | 0.904 | +0.41 | 1.92 |
| T32 | Migration, exile & homesickness | 8604 | 0.887 | -0.91 | 2.28 |
| T33 | Nature & landscape | 8604 | 0.921 | -1.18 | 3.73 |
| T34 | Everyday life & simple living | 8604 | 0.844 | +0.32 | 3.16 |
| T35 | Environmental concern | 8604 | 0.929 | -0.20 | 0.47 |
| T36 | Partying & celebration | 8604 | 0.956 | -0.34 | 2.58 |
| T37 | Escapism & fantasy | 8604 | 0.858 | -2.05 | 4.84 |
| T38 | Substance use & addiction | 8604 | 0.961 | -0.68 | 2.47 |
