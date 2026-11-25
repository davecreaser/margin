# A public-domain novel for the demo and evals, with counterfactual edits

The repo bundles a public-domain novel as its demo manuscript, and every test, fixture and eval uses it or invented text. No unpublished or copyrighted manuscript is ever committed, quoted in a test, or used as an example. Authors keep their own manuscripts outside the repo; `private/` is git-ignored for local use.

The model may have read the published novel. If so, a pipeline that answers from memory would score well on a plain question set without retrieving anything. So the eval copy of the novel has **counterfactual edits**: a small number of facts deliberately changed (a name, a sum of money, a date). Questions about those facts are only answered correctly by a pipeline that reads the manuscript. The demo copy is the novel as published.

Choosing a less famous novel limits the problem further. The choice of novel is an open question in spec 0001.
