# Grounded or silent: every citation is verified before it is shown

Margin's value is trust. An answer or finding that sounds right but isn't in the book is worse than no answer, because an author will act on it. So hallucination is handled in layers, and each layer can be measured on its own:

1. **Retrieve before generating.** The model only sees passages retrieved from the manuscript, each with a stable id (chapter and paragraph range), and is told to answer only from them.
2. **Structured output with quotes.** Answers and findings come back as structured output: every statement carries the passage id and an exact quote supporting it.
3. **Verify quotes in code.** Every quote is matched against the stored passage text, after normalising whitespace and quote marks, before anything is shown. A statement with a failed citation is dropped. If nothing grounded is left, the result is "not in the manuscript".
4. **Abstain on purpose.** "Not in the manuscript" is a first-class answer with its own eval cases (questions the book doesn't answer). Abstaining when it should is scored as highly as answering correctly.
5. **Measure it.** The evals report the failed-citation rate (how often the model invents a quote), the abstention accuracy, and accuracy on counterfactual questions (ADR 0007).

Consequence: some true answers that the model "knows" but can't quote are dropped. This is the intended trade-off.
