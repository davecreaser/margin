"""Build the eval copy of the demo novel: the published text plus counterfactual edits."""

import shutil
from pathlib import Path

import yaml

from margin.config import DEMO_DIR

HERE = Path(__file__).parent


def build(out: Path, demo: Path = DEMO_DIR) -> Path:
    spec = yaml.safe_load((HERE / "counterfactual.yaml").read_text())
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(demo, out)
    for e in spec["edits"]:
        path = out / e["file"]
        text = path.read_text(encoding="utf-8")
        found = text.count(e["find"])
        if found != e["count"]:
            raise ValueError(f"{e['file']}: {e['find']!r} occurs {found} times, not {e['count']}")
        path.write_text(text.replace(e["find"], e["replace"]), encoding="utf-8")
    for inj in spec["injections"]:
        path = out / inj["file"]
        paragraphs = path.read_text(encoding="utf-8").split("\n\n")
        hits = [i for i, p in enumerate(paragraphs) if inj["after"] in p]
        if len(hits) != 1:
            raise ValueError(f"{inj['file']}: anchor {inj['after']!r} found {len(hits)} times")
        paragraphs.insert(hits[0] + 1, " ".join(inj["text"].split()))
        path.write_text("\n\n".join(paragraphs), encoding="utf-8")
    return out
