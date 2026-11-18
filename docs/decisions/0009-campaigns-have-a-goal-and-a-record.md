---
id: "0009"
title: A campaign is an effort with a goal for one country, with its own record
status: accepted
date: 2026-11-18
supersedes: null
---

# A campaign is an effort with a goal for one country, with its own record

## Context

Decision 0003 says that a campaign is a route applied to a list of countries, and that each country gets its own run record. In practice a campaign is something else: an effort to expand one country, with a goal, made of several runs on several sources. Run records say what each run did. They do not say why a group of runs happened, which checks rejected songs, whether a limit stopped the work, or what to try next. Without this, a later campaign repeats the same runs with the same settings.

## Decision

A campaign is one effort with a goal for one country. It is made of one or more runs. This replaces the sentence on campaigns in decision 0003; the rest of decision 0003 stays.

Each campaign has a record in `countries/<ISO3>/campaigns/`: one file when it opens and one file when it closes. Commands write both files, and neither file is changed later. The record holds the goal, the open and close time, the number of songs before and after, the outcome (`complete`, `stopped` or `abandoned`) with its reason, and what the next campaign must try. A campaign cannot close without that last text. A country has at most one open campaign.

A run that starts while a campaign is open carries the id of the campaign. A run record also holds the requests sent, the songs attempted and accepted, the songs rejected by reason, and the limits that were hit.

A run that repeats a complete run with the same route, source, bulk file, delay and limits is refused, unless it states a reason.

The name of a campaign never appears in a folder name of the data.

## Consequences

- Before a new campaign, `uv run songs lyrics plan <ISO3>` shows the last run of each source and the advice of the last campaign.
- An effort for several countries is one campaign per country. Nothing joins them.
- Run records written before this decision have no campaign and no counts. They stay valid.
- A collector must count its requests, its rejections by reason and the limits it hits. A run record with these fields empty says "not recorded".
