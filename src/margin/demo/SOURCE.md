# Demo manuscript: *The Card* by Arnold Bennett (1911)

The chapters in `the-card/` are the text of *The Card, a Story of Adventure in the Five Towns* by Arnold Bennett, first published in 1911. Bennett died in 1931; the novel is in the public domain in the UK, the EU and the US.

The text comes from Project Gutenberg eBook #12986. `scripts/build_demo.py` turned it into one Markdown file per chapter:
- the Project Gutenberg header and footer, the front matter and the printer's colophon are removed
- hard-wrapped lines are joined so each paragraph is one line
- the numbered sections inside each chapter became scene breaks (`* * *`)

The words are as published. The eval uses a copy with a few deliberate changes (see `eval/ask/counterfactual.yaml` and ADR 0007); this copy has none.
