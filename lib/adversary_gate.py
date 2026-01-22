"""Adversary gate for workflow phase transitions.

Provides:
- Confidence scoring for test quality
- Objection handling with evidence requirements
- Override rules based on confidence levels
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple


class ConfidenceLevel(Enum):
    """Confidence level for adversary objections."""
    LOW = auto()      # Can override with brief rationale
    MEDIUM = auto()   # Should address, can appeal with justification
    HIGH = auto()     # Must address or appeal to user


@dataclass
class ConfidenceScore:
    """Aggregated test confidence score."""
    attack_survival: Tuple[int, int]      # (passed, total)
    mutation_survival: Tuple[int, int]    # (caught, total)
    dimension_coverage: Tuple[int, int]   # (covered, total)
    specificity: str                      # "high", "medium", "low"
    mock_fidelity: Tuple[int, int]        # (verified, total)
    redundant_tests: list = field(default_factory=list)  # Tests flagged as redundant

    @property
    def has_redundancy(self) -> bool:
        """Check if any tests were flagged as redundant."""
        return len(self.redundant_tests) > 0

    @property
    def overall(self) -> float:
        """Calculate overall confidence percentage."""
        weights = {
            "attack": 0.30,
            "mutation": 0.25,
            "dimension": 0.25,
            "specificity": 0.10,
            "mock": 0.10,
        }

        attack_pct = (self.attack_survival[0] / self.attack_survival[1] * 100
                      if self.attack_survival[1] > 0 else 0)
        mutation_pct = (self.mutation_survival[0] / self.mutation_survival[1] * 100
                        if self.mutation_survival[1] > 0 else 0)
        dimension_pct = (self.dimension_coverage[0] / self.dimension_coverage[1] * 100
                         if self.dimension_coverage[1] > 0 else 0)
        specificity_pct = {"high": 100, "medium": 70, "low": 40}.get(self.specificity, 50)
        mock_pct = (self.mock_fidelity[0] / self.mock_fidelity[1] * 100
                    if self.mock_fidelity[1] > 0 else 100)

        return (
            attack_pct * weights["attack"] +
            mutation_pct * weights["mutation"] +
            dimension_pct * weights["dimension"] +
            specificity_pct * weights["specificity"] +
            mock_pct * weights["mock"]
        )

    def format_report(self) -> str:
        """Format confidence score as readable report."""
        attack_pct = (self.attack_survival[0] / self.attack_survival[1] * 100
                      if self.attack_survival[1] > 0 else 0)
        mutation_pct = (self.mutation_survival[0] / self.mutation_survival[1] * 100
                        if self.mutation_survival[1] > 0 else 0)
        dimension_pct = (self.dimension_coverage[0] / self.dimension_coverage[1] * 100
                         if self.dimension_coverage[1] > 0 else 0)

        redundancy_line = f"\n└── Redundancy:          {len(self.redundant_tests)} flagged" if self.redundant_tests else ""
        mock_prefix = "├──" if self.redundant_tests else "└──"

        report = f"""Test Confidence: {self.overall:.0f}%
├── Attack survival:     {self.attack_survival[0]}/{self.attack_survival[1]} ({attack_pct:.0f}%)
├── Mutation survival:   {self.mutation_survival[0]}/{self.mutation_survival[1]} ({mutation_pct:.0f}%)
├── Dimension coverage:  {self.dimension_coverage[0]}/{self.dimension_coverage[1]} ({dimension_pct:.0f}%)
├── Specificity:         {self.specificity}
{mock_prefix} Mock fidelity:       {self.mock_fidelity[0]} verified, {self.mock_fidelity[1] - self.mock_fidelity[0]} assumed{redundancy_line}"""

        if self.redundant_tests:
            report += "\n\nRedundant Tests (recommend removal):"
            for rt in self.redundant_tests:
                report += f"\n  - {rt['test']}: overlaps with {rt['overlaps_with']}"

        return report


@dataclass
class AdversaryObjection:
    """An objection raised by the adversary."""
    confidence: ConfidenceLevel
    concern: str
    evidence: str = ""
    suggestion: str = ""

    def is_valid(self) -> bool:
        """Check if objection has sufficient evidence."""
        # Must have specific evidence, not just vague concern
        return bool(self.evidence and len(self.evidence) > 10)


@dataclass
class ObjectionResult:
    """Result of evaluating an objection."""
    can_proceed: bool
    requires_user_appeal: bool = False
    message: str = ""


class AdversaryGate:
    """Gate that evaluates adversary objections before phase transitions."""

    def __init__(self, confidence_threshold: float = 70.0):
        self.confidence_threshold = confidence_threshold
        self.user_overrides = 0

    def evaluate_objection(
        self,
        objection: AdversaryObjection,
        override_rationale: Optional[str] = None,
        user_approved: bool = False
    ) -> ObjectionResult:
        """Evaluate whether an objection blocks progress.

        Args:
            objection: The adversary's objection
            override_rationale: Agent's counter-argument
            user_approved: Whether user explicitly approved override
        """
        # Invalid objections (no evidence) don't block
        if not objection.is_valid():
            return ObjectionResult(can_proceed=True, message="Objection lacks evidence")

        # User approval always wins
        if user_approved:
            self.user_overrides += 1
            return ObjectionResult(can_proceed=True, message="User approved override")

        # Low confidence: can override with rationale
        if objection.confidence == ConfidenceLevel.LOW:
            if override_rationale:
                return ObjectionResult(can_proceed=True, message="Low confidence overridden")
            return ObjectionResult(
                can_proceed=False,
                message="Provide brief rationale to override low-confidence objection"
            )

        # Medium confidence: need good justification
        if objection.confidence == ConfidenceLevel.MEDIUM:
            if override_rationale and len(override_rationale) > 20:
                return ObjectionResult(can_proceed=True, message="Medium confidence overridden with justification")
            return ObjectionResult(
                can_proceed=False,
                requires_user_appeal=True,
                message="Address objection or provide detailed justification"
            )

        # High confidence: must address or user appeal
        return ObjectionResult(
            can_proceed=False,
            requires_user_appeal=True,
            message="High-confidence objection requires addressing or user appeal"
        )

    def check_confidence_threshold(self, score: ConfidenceScore) -> ObjectionResult:
        """Check if confidence score meets threshold."""
        if score.overall >= self.confidence_threshold:
            return ObjectionResult(can_proceed=True, message=f"Confidence {score.overall:.0f}% meets threshold")
        return ObjectionResult(
            can_proceed=False,
            message=f"Confidence {score.overall:.0f}% below threshold {self.confidence_threshold:.0f}%"
        )
