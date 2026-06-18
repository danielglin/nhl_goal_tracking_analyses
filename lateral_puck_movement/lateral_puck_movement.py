from dataclasses import dataclass
from typing import List

import polars as pl

import requests
import json
import time

import math

import sys
sys.path.append('../utils')
from utils import Coord, convert_api_coords, find_orig_shot_defl, find_orig_shot_nondeflection, rotate_multiple_goals

@dataclass
class ApiCoord:
    """
    A coordinate from the NHL.com API
    """
    x: float
    y: float
        
        
@dataclass
class GoalData:
    """
    Basic data for a goal
    """
    loc: ApiCoord
    shot_type: str
    event_id: int
    scoring_team_id: int
    home_team_defending_side: str

        
@dataclass
class GamePbp:
    """
    Play-by-play data for a game
    """
    game_id: int
    goals: List[GoalData]
    home_team_id: int


def main():
    """
    Calculates the total lateral puck movement for all goals
    """
    NUM_TIMESTEPS = 7
    
    # read in API data for goals, including shot type, location, game id, goal id
    # scoring team id, home team defending side, and home team id
    df_api_data_goals = pl.read_parquet('25_26_regl_season_goal_data.parquet')

    # read in dataframe with empty net goal data
    # has columns for game id, goal id, and if a goal is empty-net or not
    df_pp_loc_eng = pl.read_parquet('../rush_goals/2025_2026_coords_eng.parquet')

    df_api_data_goals_sans_engs = df_pp_loc_eng.join(df_api_data_goals, on=['game_id', 'goal_id'])
    df_api_data_goals_sans_engs = df_api_data_goals_sans_engs.filter(
        ~pl.col('is_eng')
    )

    df_api_data_goals_converted = convert_api_coords(df_api_data_goals_sans_engs)

    df_api_data_goals_rot = rotate_multiple_goals(df_api_data_goals_converted)

    df_lat_puck = lat_puck_move_df(
        df_api_data_goals_rot,
        num_timesteps=NUM_TIMESTEPS
    )

    df_lat_puck = df_lat_puck.select(
        pl.col('game_id'),
        pl.col('goal_id'),
        pl.col('lat_puck_move'),
    )
    
    # export the result
    df_lat_puck.write_csv('lat_puck_move_7.csv')


def get_goal_data(game_id: int) -> GamePbp:
    """
    Pulls goal data from the play-by-play endpoint
    
    PARAMETERS:
        - game_id (int): the game id to pull goal data for
    
    RETURNS:
        - game_pbp (GamePbp): goal data along with game id and home team id
    """
    TOO_MANY_REQS_CODE = 429
    SECS_TO_WAIT = 1
    
    r = requests.get(f'https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play')
    
    # handle too many reqs errors
    while (r.status_code == TOO_MANY_REQS_CODE):
        time.sleep(SECS_TO_WAIT) # in seconds
        r = requests.get(f'https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play')
        
    pbp_str = r.content.decode()
    dict_pbp = json.loads(pbp_str)

    # get game-level data
    home_team_id = dict_pbp['homeTeam']['id']
    l_plays = dict_pbp['plays']

    l_goals = []
    for dict_play in l_plays:
        if dict_play['typeDescKey']=='goal':
            
            # get goal-level data
            goal_id = dict_play['eventId']
            shot_type = dict_play.get('details', {}).get('shotType', 'MISSING')
            
            loc_x = dict_play['details']['xCoord']
            loc_y = dict_play['details']['yCoord']
            api_coord = ApiCoord(x=loc_x, y=loc_y)
            
            scoring_team_id = dict_play['details']['eventOwnerTeamId']
            home_team_defending_side = dict_play['homeTeamDefendingSide']
            
            goal_data = GoalData(
                loc=api_coord,
                shot_type=shot_type,
                event_id=goal_id,
                scoring_team_id=scoring_team_id,
                home_team_defending_side=home_team_defending_side
            )
            l_goals.append(goal_data)
    
    # organize the goal data into a GamePbp
    return GamePbp(
        game_id=game_id,
        goals=l_goals,
        home_team_id=home_team_id
    )


# def convert_api_coords(df_api_goals: pl.DataFrame, x_col: str = 'api_x', y_col: str = 'api_y') -> pl.DataFrame:
#     """
#     Converts API coordinates to animation coordinates
    
#     PARAMETERS:
#         - df_api_goals (polars.DataFrame): dataframe of shots
#         - x_col (str): the column that has x coordinates
#         - y_col (str): the column that has y coordinates
    
#     RETURNS:
#         - df_converted (polars.DataFrame): dataframe with 
#             converted x in the 'anim_x' column and the 
#             converted y in the 'anim_y' column
#     """
#     OUTPUT_X_COL = 'anim_x'
#     OUTPUT_Y_COL = 'anim_y'
#     FT_TO_ANIM_X_FACTOR = 12 # from 2400/200
#     FT_TO_ANIM_Y_FACTOR = 1015/85
    
#     df_converted = df_api_goals.with_columns(
#         ((pl.col(x_col)+100)*FT_TO_ANIM_X_FACTOR).alias(OUTPUT_X_COL),
#         ((pl.col(y_col)*-1 + 40)*FT_TO_ANIM_Y_FACTOR).alias(OUTPUT_Y_COL)
#     )
#     return df_converted


# def rotate_goal_coords(
#     x: float,
#     y: float,
#     scoring_team_id: int,
#     home_team_id: int,
#     home_team_defending_side: str
# ) -> tuple[Coord, bool]:
#     """
#     Rotates the coordinates for a single coordinate
    
#     PARAMETERS:
#         - x (float): the x coordinate
#         - y (float): the y coordinate
#         - scoring_team_id (int): id of the team that scored
#         - home_team_id (int): id of the home team
#         - home_team_defending_side (str): which side the
#             home team's goal is on
#             - Should be 'left' or 'right'
    
#     RETURNS:
#         - rotated_coord (Coord): the rotated data
#         - is_rot (bool): True if the coordinate was rotated,
#             otherwise False
#     """
#     MAX_X = 2400.
#     MAX_Y = 1015.

#     # det if need to rotate
#     if home_team_defending_side == 'left':
#         away_team_defending_side = 'right'
#     elif home_team_defending_side == 'right':
#         away_team_defending_side = 'left'
#     else:
#         raise ValueError(f'Invalid home team defending side {home_team_defending_side}.  Needs to be either "left" or "right"')

#     # home team scores
#     if scoring_team_id == home_team_id:
#         scoring_side = away_team_defending_side
#     # away team scores
#     else:
#         scoring_side = home_team_defending_side
    
#     x_pos = float(min(x, MAX_X))
#     x_pos = max(x_pos, 0)

#     y_pos = min(y, MAX_Y)
#     y_pos = max(y_pos, 0)
    
#     if scoring_side == 'left':
#         rot_x_pos = MAX_X - x_pos
#         rot_y_pos = MAX_Y - y_pos
#         coord = Coord(x=rot_x_pos, y=rot_y_pos)
#         is_rot = True
#     else:
#         coord = Coord(x=x_pos, y=y_pos)
#         is_rot = False

#     return coord, is_rot


# def dist(x_1: float, y_1: float, x_2: float, y_2: float) -> float:
#     """
#     Returns the distance between two coordinates
    
#     PARAMETERS:
#         - x_1 (float): x coordinate of first location
#         - y_1 (float): y coordinate of first location
#         - x_2 (float): x coordinate of second location
#         - y_2 (float): y coordinate of second location
    
#     RETURNS:
#         - distance (float): the distance between the two
#             coordinates
#     """
#     return ((x_1 - x_2) ** 2 + (y_1 - y_2) ** 2) ** 0.5

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


def lat_puck_move_df(df_goals: pl.DataFrame, num_timesteps: int) -> pl.DataFrame:
    """
    Estimates the lateral puck movement for all goals in a dataframe
    
    PARAMETERS:
        - df_goals (polars.DataFrame): dataframe with the following columns:
            - x_coordinates
            - y_coordinates
            - rot_x
            - rot_y
            - shot_type
        - num_timesteps (int): how many timesteps to go back from the original shot
            to calculate lateral puck movement
            
    RETURNS:
        - df_lat_movement (polars.DataFrame): df_goals with an additional
            "lat_puck_move" column for the total lateral puck movement
    """
    ONE_ANIM_UNIT_IN_FT = 85. / 1015.
    l_lat_puck_move = []
    
    for row in df_goals.rows(named=True):
        x_coords = row['x_coordinates']
        y_coords = row['y_coordinates']
        shot_x = row['rot_x']
        shot_y = row['rot_y']
        shot_type = row['shot_type']
        
        l_coords = list(zip(x_coords, y_coords))
        
        # need separate logic to find backwards index of deflected shots
        if shot_type in ('deflected', 'tip-in'):
            backward_shot_ind = find_orig_shot_defl(
                l_coords, shot_x, shot_y
            )
        else:
            backward_shot_ind = find_orig_shot_nondeflection(
                l_coords, shot_x, shot_y
            )
        if backward_shot_ind is None:
            print(f'No shot found for {row["game_id"]}, {row["goal_id"]}')
            l_lat_puck_move.append(None)
            continue
        # calculate total lateral puck movement for the goal
        # move back from the original shot
        total_lat_move = 0
        last_backward_ind = min(
            len(l_coords),
            backward_shot_ind+num_timesteps+1
        )
        for i in range(backward_shot_ind+1, last_backward_ind):
            y = l_coords[::-1][i][1] # 1 ind is to get just the y coordinate
            prev_y = l_coords[::-1][i-1][1]
            total_lat_move += abs(y-prev_y)
        
        total_lat_move = total_lat_move * ONE_ANIM_UNIT_IN_FT # convert to feet
        l_lat_puck_move.append(total_lat_move)
        
    df_lat_movement = df_goals.with_columns(
        pl.Series(values=l_lat_puck_move, name='lat_puck_move')
    )
    return df_lat_movement


if __name__ == '__main__':
    main()