"""Golden set: the cases the system is measured against.

Cases live in YAML under evals/cases/, one file per manual, and are versioned
with the code. They are input data that evolves alongside the system - change
the router prompt and the cases covering it belong in the same commit - and a
diff has to show what question was added and what answer was called correct.

Two details that look small and are not:

* Pages, never chunk ids. A chunk id is a uuid4 minted on every insert, so
  re-ingesting with a different chunk size invalidates the whole golden set -
  precisely when it is most needed. Page numbers come from the PDF and survive
  any change to the pipeline.

* Cases whose answer is NOT in the manual. Without them, a system that invents
  a plausible answer for everything scores well: nothing would be measuring
  honesty.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

CASES_DIR = Path(__file__).resolve().parents[3] / "evals" / "cases"


class EvalCase(BaseModel):
    """One question with everything needed to grade the answer."""

    id: str
    question: str

    # The appliance the question is about. Retrieval is scoped to it, the same
    # way the application does after the user picks a model.
    #
    # brand and model rather than product_id, for the same reason pages are used
    # instead of chunk ids: an id is a uuid that changes when the catalogue is
    # rebuilt, and the golden set has to survive that.
    brand: str
    model: str

    intent: str | None = None

    # False when the manual does not cover this. Then the only correct
    # behaviour is to say so, and that is what gets measured.
    answerable: bool = True

    # Pages where the answer lives. Retrieval is scored on whether any returned
    # chunk covers one of them.
    expected_pages: list[int] = Field(default_factory=list)

    # Reference answer in prose. The judge compares meaning against this, which
    # is why it is not a keyword list.
    expected_answer: str | None = None

    # Facts that must survive any rewording. Cheap deterministic signal next to
    # the judge, and a way to catch a judge being too generous.
    key_facts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_shape(self) -> "EvalCase":
        if self.answerable and not self.expected_answer:
            raise ValueError(f"{self.id}: an answerable case needs expected_answer")
        if not self.answerable and self.expected_pages:
            raise ValueError(f"{self.id}: unanswerable cases cannot expect pages")
        return self


def load_cases(directory: Path | None = None) -> list[EvalCase]:
    """Read every case file, failing loudly on a malformed one.

    A broken case silently skipped would quietly shrink the golden set, and the
    metrics would improve for the wrong reason.
    """
    directory = directory or CASES_DIR
    cases: list[EvalCase] = []

    for path in sorted(directory.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text()) or []
        cases.extend(EvalCase(**entry) for entry in payload)

    seen = {case.id for case in cases}
    if len(seen) != len(cases):
        raise ValueError("Duplicate case ids across files")

    return cases
