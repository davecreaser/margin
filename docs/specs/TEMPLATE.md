# NNNN: Feature name

Status: draft | approved | in progress | done
Issue: #N (if any)

## Problem

Who has what problem today, in their words. One paragraph.

## User stories

- **US-1** As a … I want … so that …

## Acceptance criteria

Each criterion is testable: a reviewer or QA can show it passing or failing.

- **AC-1** Given … when … then …

Traceability: US-1 → AC-…

## Eval

Required for any feature with a model step.

- **Cases:** which cases are added, including the empty case, abstentions, adversarial text and counterfactuals.
- **Grading:** how each case is graded on results, not wording.
- **Metrics and bar:** the metrics reported, and the bar this spec must meet before it ships.
- **Cost:** the worst-case cost of one full run.

## Non-goals

What this deliberately does not do (yet).

## Grounding & safety

- Is every new statement shown to the user cited and verified (ADR 0001)? What does the feature show when nothing is grounded?
- What manuscript text goes to the model, and is it tagged as data (ADR 0005)?
- Does it generate any prose for the author? (It mustn't.)
- What is the spend per request, and what caps it?
- Public repo: are the new fixtures and examples only from the demo novel or invented, with no secrets?

## Interface

The CLI commands, options and exact output, including:
- an empty index
- not in the manuscript
- a model or Elasticsearch error
- the cost confirmation
- a 150,000-word manuscript

Also any new HTTP endpoints.

## Open questions

Numbered. Each is resolved into the Decisions section before approval.

## Decisions

- YYYY-MM-DD: the decision, and why.
