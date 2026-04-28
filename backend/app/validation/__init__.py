"""Validation + learning loop.

After a suggestion's target_date passes, this layer:
  - measures what actually happened (price + dividends + FX)
  - scores the suggestion correct / incorrect / partial
  - stores a SuggestionValidation row + appends to the data repo
  - once ≥50 validations exist, fits a confidence-calibration model
    (isotonic regression) and recalibrates per-cell module weights.

Public surface:
    from app.validation.sweep import sweep_due_validations
    from app.validation.calibration import maybe_recalibrate
"""

from app.validation.outcome import OutcomeResult, compute_outcome

__all__ = ["OutcomeResult", "compute_outcome"]
