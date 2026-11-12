# Exhibits

Every figure and table that the paper or the presentation uses ([decision 0004](../docs/decisions/0004-paper-presentation-and-exhibits.md)).

```
exhibits/
  figures/    PNG files at 300 dpi
  tables/     tables as text files (`.tex`)
```

## Rules

- Code writes every file here. Do not edit an exhibit by hand, and do not paste a number from one into a document.
- A figure follows [`docs/standards/figures.md`](../docs/standards/figures.md): it calls `apply_paper_matplotlib` and saves with `save_png`.
- A file name says what the exhibit shows, in lower case with underscores: `topic_shares_by_decade.png`. No dates and no version numbers in names; Git keeps the history.
- An exhibit holds no lyric text and no private identifier. This repository is public.
- Trial figures and other scratch results go to `outputs/`, which is local and not in Git.

The paper and the presentation live in `overleaf/`, which is local and not in Git. They read copies of these files.

A list of exhibits, with the command that makes each one and the document that uses it, arrives with the first exhibit.
