# LlamaIndex for ingestion; our own code for retrieval and the reasoning steps

LlamaIndex does the ingestion plumbing it is good at:
- the document and node model: each chapter is a `Document`, each passage a `TextNode` with its chapter and paragraph range as metadata
- splitting, through our own `NodeParser` subclass (`ParagraphPassageParser`), because citations need paragraph ranges and passages must never split a paragraph or cross a chapter, which the built-in splitters don't guarantee
- local embeddings through its FastEmbed integration (ONNX on CPU, no PyTorch in the image)

Our own code does the rest:
- **Loading files.** Chapter detection (a folder of files, Markdown headings, "Chapter 3" or "CHAPTER III" lines, .docx heading styles) is a few dozen lines and has to report "no chapters found" precisely.
- **Elasticsearch.** Writing the index (a fresh index per ingest, swapped in by alias) and the hybrid query. Reciprocal rank fusion runs in Python over a BM25 and a kNN query, so each side's ranking is visible in `--show-passages` and comparable in the eval.
- **The steps that decide what the user sees:** answer a question, extract claims, judge a claim against its passages, name a habit. Each is a plain Python function with one prompt and one typed output.

Why: the reasoning steps and the retrieval query are what the evals measure and what changes tune. They need to be readable in one file, unit-testable with a fake model or fixed vectors, and free of framework defaults that change between versions. A framework's agent, chain or vector-store abstraction would hide exactly the parts that matter most.

If ingestion outgrows LlamaIndex or gets in the way, it can be replaced without touching retrieval or the reasoning steps.
