import time
from pathlib import Path

from margin import manuscript as ms
from margin import passages as ps
from margin.steps.answer import build_prompt
from tests.fakes import invented_text


def test_150k_word_manuscript_splits_fast_and_prompts_stay_bounded(tmp_path: Path) -> None:
    paragraphs = invented_text(150_000)
    per_chapter = len(paragraphs) // 40
    for n in range(40):
        chunk = paragraphs[n * per_chapter : (n + 1) * per_chapter]
        (tmp_path / f"{n:02d}.md").write_text(f"# Chapter {n + 1}\n\n" + "\n\n".join(chunk))
    started = time.perf_counter()
    m = ms.load(tmp_path)
    passages = ps.split(m, 150, 400)
    assert time.perf_counter() - started < 10
    assert m.words > 140_000 and len(m.chapters) == 40
    # Prompt size depends on the passage count, not on the manuscript's length.
    longest = sorted(passages, key=lambda p: -len(p.text))[:8]
    assert len(build_prompt("A question?", longest).split()) < 8 * 600


def test_a_huge_paragraph_is_capped_in_the_prompt() -> None:
    from margin.passages import Passage

    huge = Passage(1, "One", 1, 1, " ".join(["word"] * 18_000))
    assert len(build_prompt("Q?", [huge] * 8).split()) < 8 * 900
