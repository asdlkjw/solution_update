"""v1 pipeline - uses existing fixer.py process_single_problem as-is"""
from app.core.fixer import process_single_problem
from app.core.pipelines.registry import register_pipeline

register_pipeline("v1", process_single_problem)
