from dataclasses import dataclass
from typing import Optional

@dataclass
class Violations:
    ''' Track violations for scoring. This is per code base scope'''
    scope: Optional[str] = None
    magic_numbers: int = 0
    untested_boundaries: int = 0
    redundant_iterations: int = 0
    comprehension_miss: int = 0
    polling_loop: int = 0
    busy_wait: int = 0

violations_tracker = Violations("global")