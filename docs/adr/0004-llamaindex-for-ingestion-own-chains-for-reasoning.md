# LlamaIndex for ingestion; our own code for the answer and check chains

LlamaIndex does the plumbing it is good at: loading files, splitting chapters into paragraph-aligned passages, embedding them, and writing them to Elasticsearch.

The steps that decide what the user sees are plain, explicit Python functions, one prompt and one typed output each:
- answer a question
- extract claims
- judge a claim against its passages
- name a habit

Why: these steps are what the evals measure and what prompt changes tune. They need to be readable in one file, unit-testable with a fake model, and free of framework defaults that change between versions. A framework's agent or chain abstraction would hide exactly the parts that matter most.

If ingestion outgrows LlamaIndex or gets in the way, it can be replaced without touching the reasoning steps.
