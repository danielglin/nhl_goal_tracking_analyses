# utils.py
# def "helper types" to org coords
from dataclasses import dataclass
import math
from typing import List

import polars as pl

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


def convert_api_coords(df_api_goals: pl.DataFrame, x_col: str = 'api_x', y_col: str = 'api_y') -> pl.DataFrame:
    """
    Converts API coordinates to animation coordinates
    
    PARAMETERS:
        - df_api_goals (polars.DataFrame): dataframe of shots
        - x_col (str): the column that has x coordinates
        - y_col (str): the column that has y coordinates
    
    RETURNS:
        - df_converted (polars.DataFrame): dataframe with 
            converted x in the 'anim_x' column and the 
            converted y in the 'anim_y' column
    """
    OUTPUT_X_COL = 'anim_x'
    OUTPUT_Y_COL = 'anim_y'
    FT_TO_ANIM_X_FACTOR = 12 # from 2400/200
    FT_TO_ANIM_Y_FACTOR = 1015/85
    
    df_converted = df_api_goals.with_columns(
        ((pl.col(x_col)+100)*FT_TO_ANIM_X_FACTOR).alias(OUTPUT_X_COL),
        ((pl.col(y_col)*-1 + 40)*FT_TO_ANIM_Y_FACTOR).alias(OUTPUT_Y_COL)
    )
    return df_converted


def rotate_goal_coords(
    x: float,
    y: float,
    scoring_team_id: int,
    home_team_id: int,
    home_team_defending_side: str
) -> tuple[Coord, bool]:
    """
    Rotates the coordinates for a single coordinate
    
    PARAMETERS:
        - x (float): the x coordinate
        - y (float): the y coordinate
        - scoring_team_id (int): id of the team that scored
        - home_team_id (int): id of the home team
        - home_team_defending_side (str): which side the
            home team's goal is on
            - Should be 'left' or 'right'
    
    RETURNS:
        - rotated_coord (Coord): the rotated data
        - is_rot (bool): True if the coordinate was rotated,
            otherwise False
    """
    MAX_X = 2400.
    MAX_Y = 1015.

    # det if need to rotate
    if home_team_defending_side == 'left':
        away_team_defending_side = 'right'
    elif home_team_defending_side == 'right':
        away_team_defending_side = 'left'
    else:
        raise ValueError(f'Invalid home team defending side {home_team_defending_side}.  Needs to be either "left" or "right"')

    # home team scores
    if scoring_team_id == home_team_id:
        scoring_side = away_team_defending_side
    # away team scores
    else:
        scoring_side = home_team_defending_side
    
    x_pos = float(min(x, MAX_X))
    x_pos = max(x_pos, 0)

    y_pos = min(y, MAX_Y)
    y_pos = max(y_pos, 0)
    
    if scoring_side == 'left':
        rot_x_pos = MAX_X - x_pos
        rot_y_pos = MAX_Y - y_pos
        coord = Coord(x=rot_x_pos, y=rot_y_pos)
        is_rot = True
    else:
        coord = Coord(x=x_pos, y=y_pos)
        is_rot = False

    return coord, is_rot


def rotate_multiple_goals(df_api_data_goals_converted: pl.DataFrame):
    """
    For a dataframe of goal shots, rotate the shot locations for all goals as 
    needed

    PARAMETERS:
        - df_api_data_goals_converted (polars.DataFrame): dataframe with the 
            following columns:
            - anim_x: x coordinate in the tracking data coordinate system
            - anim_y: y coordinate in the tracking data coordinate system
            - scoring_team_id: the id of the scoring team
            - home_team_id: the id of the home team
            - home_team_defending_side: the side the home team's goal is on
    
    RETURNS:
        - df_api_data_goals_rot (polars.DataFrame): datafarme with the following
            additional columns:
            - rot_x: the x coordinate after possibly rotating
            - rot_y: the y coordinate after possibly rotating
            - is_rot: True if the coordinate was rotated, False otherwise
    """
    rot_x = []
    rot_y = []
    rot_bools = []

    for row in df_api_data_goals_converted.rows(named=True):
        x = row['anim_x']
        y = row['anim_y']
        scoring_team_id = row['scoring_team_id']
        home_team_defending_side = row['home_team_defending_side']
        home_team_id = row['home_team_id']
        rot_coord, is_rot = rotate_goal_coords(
            x, y, 
            scoring_team_id=scoring_team_id, 
            home_team_defending_side=home_team_defending_side, 
            home_team_id=home_team_id
        )
        rot_x.append(rot_coord.x)
        rot_y.append(rot_coord.y)
        rot_bools.append(is_rot)

    df_api_data_goals_rot = df_api_data_goals_converted.with_columns(
        pl.Series(values=rot_x, name='rot_x'),
        pl.Series(values=rot_y, name='rot_y'),
        pl.Series(values=rot_bools, name='is_rot')
    )
    return df_api_data_goals_rot


def dist(x_1: float, y_1: float, x_2: float, y_2: float) -> float:
    """
    Returns the distance between two coordinates
    
    PARAMETERS:
        - x_1 (float): x coordinate of first location
        - y_1 (float): y coordinate of first location
        - x_2 (float): x coordinate of second location
        - y_2 (float): y coordinate of second location
    
    RETURNS:
        - distance (float): the distance between the two
            coordinates
    """
    return ((x_1 - x_2) ** 2 + (y_1 - y_2) ** 2) ** 0.5


def angle(coord_1: Coord, coord_2: Coord, coord_3: Coord) -> float:
    """
    Calculates the angle two line segments
    """
    # express line segments as vectors
    vec_1 = (coord_2.x - coord_1.x, coord_1.y - coord_2.y)
    vec_2 = (coord_3.x - coord_2.x, coord_2.y - coord_3.y)

    # calculate the dot product
    dot_prod = vec_1[0] * vec_2[0] + vec_1[1] * vec_2[1]
    
    mag_1 = (vec_1[0]**2 + vec_1[1]**2)**0.5
    mag_2 = (vec_2[0]**2 + vec_2[1]**2)**0.5
    
    cos = dot_prod/(mag_1 * mag_2)
    cos = min(max(cos, -1), 1) # clip between -1 and 1
    
    # calculate the angle in radians
    angle_rad = math.acos(cos)
    
    # convert to degrees
    angle_deg = math.degrees(angle_rad)%360
    
    if (angle_deg-180) >= 0:
        return 360 - angle_deg
    else:
        return angle_deg


def find_orig_shot_nondeflection(
    l_coords: List[tuple[float, float]], 
    shot_x: float, 
    shot_y: float, 
) -> int|None:
    """
    Finds the original shot's location for a non-deflection goal
    
    PARAMETERS:
        - l_coords (list of tuples of 2 floats): puck tracking data
        - shot_x (float): shot x coordinate converted from API coordinates to animation coordinates
        - shot_y (float): shot y coordinate converted from API coordinates to animation coordinates
    
    RETURNS:    
        - orig_goal_backward_ind (int): index for the backward coordinate list
            for the original shot
            Is None if the original shot can't be found in the tracking data
    """
    DIST_DIFF_THRES = 120
    TIMESTEPS_POST_INIT_THRES = 3 # the number of steps to continue after
                                  # finding a location close enough to the API shot location
    
    # go thr/ goal backward
    min_dist_fr_api_shot = 99999
    orig_goal_backward_ind = None
    num_timesteps_post_init = 0  # the number of timesteps that have passed since finding
                                 # the first tracking location close to the API shot location
    
    for i, (x, y) in enumerate(l_coords[::-1]):

        dist_fr_api_shot = dist(x, y, shot_x, shot_y)
        
        # update info about the shot location
        if (dist_fr_api_shot < min_dist_fr_api_shot) and (dist_fr_api_shot < DIST_DIFF_THRES):
            min_dist_fr_api_shot = dist_fr_api_shot

            # update the shot location based on the puck's tracking data
            orig_goal_backward_ind = i
        
        if orig_goal_backward_ind is not None:
            num_timesteps_post_init += 1

        # early return so don't have to go thr/ the rest of the tracking data
        if num_timesteps_post_init > TIMESTEPS_POST_INIT_THRES:
            return orig_goal_backward_ind
        
    if orig_goal_backward_ind is None:
        return None
    else:
        return orig_goal_backward_ind

def find_orig_shot_defl(l_coords: List[tuple[float, float]], shot_x: float, shot_y: float) -> int|None:
    """
    Finds the original shot's location for a deflection goal
    
    PARAMETERS:
        - l_coords (list of tuples of 2 floats): puck tracking data
        - shot_x (float): shot x coordinate converted from API coordinates to animation coordinates
        - shot_y (float): shot y coordinate converted from API coordinates to animation coordinates
        - num_timesteps (int): how many timesteps to go back from the original shot
            to calculate lateral puck movement
    
    RETURNS:    
        - orig_goal_backward_ind (int): index for the backward coordinate list
            for the original shot
    """
    DIST_DIFF_THRES = 47
    ANGLE_THRES = 20

    MAX_SHOT_POS_NUM_TIMESTEPS = 10 # max number of timesteps above which we won't assign the shot's api
                                    # loc to the timepstep's anim loc

    # go thr/ goal backward
    min_dist_fr_api_shot = 99999
    tip_backwards_timestep = None
    orig_goal_backward_ind = None
    for i, (x, y) in enumerate(l_coords[::-1]):

        dist_fr_api_shot = dist(x, y, shot_x, shot_y)

        # update info about the tip
        if (dist_fr_api_shot < min_dist_fr_api_shot) and ((i+1) <= MAX_SHOT_POS_NUM_TIMESTEPS):
            min_dist_fr_api_shot = dist_fr_api_shot

            # update the tip loc based on the puck's tracking data
            tip_backwards_timestep = i

        # update info about the original shot
        prev_x = l_coords[::-1][i-1][0]
        prev_y = l_coords[::-1][i-1][1]
        x_two_steps_before = l_coords[::-1][i-2][0]
        y_two_steps_before = l_coords[::-1][i-2][1]

        next_x = l_coords[::-1][i+1][0]
        next_y = l_coords[::-1][i+1][1]
        dist_diff = abs(dist(x, y, prev_x, prev_y)-dist(prev_x, prev_y, x_two_steps_before, y_two_steps_before))
        angle_at_spot = angle(
            Coord(x=next_x, y=next_y),
            Coord(x=x, y=y),
            Coord(x=prev_x, y=prev_y),
        )

        if ((tip_backwards_timestep is not None) and\
            (i > (tip_backwards_timestep+1))) and\
            ((dist_diff>DIST_DIFF_THRES) or\
            (angle_at_spot>ANGLE_THRES)):
            orig_goal_backward_ind = i
            break

    return orig_goal_backward_ind