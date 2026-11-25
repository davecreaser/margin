---
name: feature
description: Take a feature from idea (or GitHub issue) to a reviewed, tested pull request, with the product, reviewer and qa agents.
disable-model-invocation: true
argument-hint: <idea in words, or #issue-number>
---

Run a feature through the project's workflow. The user approves at one **gate**, the spec; everything after runs without asking. The spec's acceptance criteria (AC-1, AC-2, …) and its Eval section are the thread through every step.

Input: `$ARGUMENTS`, an idea in words or a GitHub issue (`#12`).

1. **Set up.** Next spec number: one above the highest in `docs/specs/`. From an up-to-date `main`, create branch `feat/NNNN-slug`.
2. **Spec (product agent) → gate.** Dispatch the product agent with the input and `docs/specs/NNNN-slug.md`. Show the user the summary, the acceptance criteria and the eval bar, then ask the open questions (AskUserQuestion, recommended answer first). Record each answer in Decisions, set `Status: approved`, and commit.
3. **Build.** Test-first, in small commits, one acceptance criterion (or a slice of one) at a time. Follow `CLAUDE.md`. Add the eval cases and graders with the step they measure. Done when every criterion is implemented and the checks pass.
4. **Eval.** If the feature has a model step, run its eval's dry run, then one real run within the spec's cost. Put the numbers in the PR. If the bar isn't met, say so plainly and ask the user whether to iterate or ship as is.
5. **Review (reviewer agent).** Run it once. Fix every blocking and should-fix finding, or record in the spec why not. Run it again only on fixes to blocking findings.
6. **QA (qa agent).** Run it once. Fix failing criteria and bugs above nit, then re-run only the affected tests.
7. **Pull request.**
   - Update `README.md`: what a user can now do (a short section in "What it does", the command table, eval numbers). If the feature shows something in the page, add or refresh a screenshot in `docs/images/` taken from the demo novel or invented text only, never a private manuscript.
   - Set `Status: done`, push the branch, and open a PR with: a summary, the acceptance criteria as a checklist with evidence, the eval numbers, and a link to the spec (`Closes #N`).
   - Before pushing, scan the diff for secrets and personal details.
   - Watch CI to green.

The user reviews and merges.
