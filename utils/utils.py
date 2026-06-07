# utils.py
# def "helper types" to org coords
from dataclasses import dataclass
from typing import List


@dataclass
class Coord:
    x: float
    y: float


@dataclass
class Instant:
    """
    The coord and timestamp for a given instance in time
    """
    coord: Coord
    timestamp: str
        
@dataclass
class GoalCoords:
    instances: List[Instant]
    game_id: str # for debugging
    goal_id: str # for debugging
    rotated: bool # for debugging