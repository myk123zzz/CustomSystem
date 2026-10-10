"""Offline evaluation primitives for the customer-service workflow."""

from evaluation.dataset import EvalCase, load_cases
from evaluation.metrics import EvalReport, evaluate_results

__all__ = ["EvalCase", "EvalReport", "evaluate_results", "load_cases"]
