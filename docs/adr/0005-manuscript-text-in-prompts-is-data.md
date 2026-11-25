# Manuscript text in prompts is data, never instructions

Everything from a manuscript (passages, notes, a checked chapter) and every user question goes into prompts inside XML tags, XML-escaped. Every system prompt says that tagged content is data to read, never instructions to follow.

Fiction makes this sharper than usual: characters give orders, and a manuscript can legitimately contain "ignore all previous instructions" as dialogue. So nothing is rejected for its wording. Instead, the output is structured (ADR 0001), so a hijacked response can only produce statements, and statements without verified citations are dropped.

The Ask eval includes a passage containing injected instructions, to check this holds.
