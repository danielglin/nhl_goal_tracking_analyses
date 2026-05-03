from dataclasses import dataclass
from typing import Dict, List

import polars as pl

import requests
import json
import time


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
    game_id: str 
    goal_id: str 
    rotated: bool 


def import_pp_data(df_pp_loc: pl.DataFrame) -> Dict[str, GoalCoords]:
    """
    Imports pre-processed location data into a dictionary that maps
    concatenated game and goal id's to GoalCoords's
    
    PARAMETERS:
        - df_pp_loc (polars.DataFrame): imported pre-processed data

    RETURNS:
        - dict_goal_pp_loc (dict): keys are concatenated game goal id's, like
            '2024020004_746', and values are GoalCoords's
    """
    dict_goal_pp_loc = {} # keys are game goal id's, values are lists of coord.s

    for row in df_pp_loc.rows(named=True):
        game_id = row['game_id']
        goal_id = row['goal_id']
        x = row['x_coordinates']
        y = row['y_coordinates']

        if (len(x)!=len(y)):
            print(f'Mismatching lengths for x and y coordinates for game {game_id} goal {goal_id}')
            continue

        # combine x and y coordinates into a single list of coordinates
        l_goal_instances = []
        i = 0
        for x_i, y_i in zip(x, y):
            coord = Coord(x=x_i, y=y_i)

            # use a dummy timestamp in order to make an Instant
            instant = Instant(coord=coord, timestamp=str(i))
            i += 1

            l_goal_instances.append(instant)
        gc = GoalCoords(instances=l_goal_instances, game_id=game_id, goal_id=goal_id, rotated=False)
        dict_goal_pp_loc[f'{game_id}_{goal_id}'] = gc
    return dict_goal_pp_loc


def is_eng(game_id: int, goal_id: int) -> bool:
    """
    Returns True if the goal is an empty-net goal, False
    otherwise
    
    Data is from the NHL's replay endpoint
    
    PARAMETERS:
        - game_id (int): the game id for the goal
        - goal_id (int): the goal id
    
    RETURNS:
        - is_eng (bool): True for an empty-net goal, False
            if the goal isn't an empty-net goal
    """
    TOO_MANY_REQS_CODE = 429
    SECS_TO_WAIT = 1
    
    r = requests.get(f'https://api-web.nhle.com/v1/ppt-replay/goal/{game_id}/{goal_id}')
    
    # handle too many reqs errors
    while (r.status_code == TOO_MANY_REQS_CODE):
        time.sleep(SECS_TO_WAIT) # in seconds
        r = requests.get(f'https://api-web.nhle.com/v1/ppt-replay/goal/{game_id}/{goal_id}')
        
    replay_str = r.content.decode()
    replay = json.loads(replay_str)
    goal_mod = replay['goal']['goalModifier']

    if goal_mod == 'empty-net':
        return True
    else:
        return False

def export_eng_data(df_pp_loc: pl.DataFrame, output_path: str):
    """
    Fetches empty-net goal data, combines it with puck location data,
    and writes out result to a parquet file

    PARAMETERS:
        - df_pp_loc (polars.DataFrame): a dataframe with both game and goal ids
        - output_path (str): where to save the empty-net deata
    
    RETURNS:
        - None
    """
    l_is_eng = []
    i = 0

    for row in df_pp_loc.rows(named=True):
        game_id = row['game_id']
        goal_id = row['goal_id']
        try:
            l_is_eng.append(is_eng(game_id=game_id, goal_id=goal_id))
        except Exception as e:
            print(f'error: {e} for game {game_id}, goal {goal_id}')
            l_is_eng.append(str(e))
        i += 1
        print(f'Done with {i} out of {len(df_pp_loc)} goals')
    
    df_pp_loc_eng = df_pp_loc.with_columns(
        pl.lit(value=l_is_eng).alias('is_eng')
    )
    df_pp_loc_eng.write_parquet(output_path)


def find_rush_goals(dict_goal_pp_loc: Dict[str, GoalCoords]) -> pl.DataFrame:
    """
    Finds the rush goals from a dictionary of puck GoalCoords based on x distance
    traveled from the minimum x coordinate, number of timesteps in the offensive
    zone, and the number of timesteps beyond the goal line

    PARAMETERS:
        - dict_goal_pp_loc (dict): keys are strings with the format 
            "<game id>_<goal_id>", values are the puck GoalCoords
    
    RETURNS:
        - df_rush_goals (polars.DataFrame): dataframe with the rush goals
            Has the following columns:
                - game_ids (i64): the game id
                - goal_ids (i64): the goal id
                - x_dists (f64): the puck's x distance from the minimum x 
                    coordinate of the puck
                - off_zone_times (i64): the number of timesteps the puck spent
                    in the offensive zone
                    If the puck exited the offensive zone, this counter gets reset
                - beyond_goal_line_times (i64): the number of timesteps the puck
                    spend beyond the goal line
    """
    MIN_X_DIST = 800. # x distance traveled from the minimum x coordinate
    OFF_ZONE_MAX_TIMESTEPS = 40 # num of timesteps in the offensive zone
    PAST_GOAL_LINE_MAX_TIMESTEPS = 9 # num of timesteps beyond the goal line

    OFF_ZONE_X = 1500. # x location of offensive blue line
    GOAL_LINE_X = 2245. # x location of the goal line

    game_ids = []
    goal_ids = []
    x_dists = []
    off_zone_times = []
    beyond_goal_line_times = []
    ppt_url = []

    for game_goal_id in dict_goal_pp_loc:
        goal_coords = dict_goal_pp_loc[game_goal_id]
        
        min_x_coord = Coord(x=99999., y=0.)
        num_timesteps_in_ozone = 0
        num_timesteps_beyond_goal_line = 0
        
        if (len(goal_coords.instances) == 0):
            continue
        
        for instance in goal_coords.instances:
            coord = instance.coord
            
            # go thr/ the coords in a goal to find the min x coord
            if coord.x < min_x_coord.x:
                min_x_coord = Coord(x=coord.x, y=coord.y)
            
            # goal line check
            if coord.x >= GOAL_LINE_X:
                num_timesteps_beyond_goal_line += 1
            
            # accumulate number of timesteps spent in the offensive zone
            # there may be an issue where the puck goes out of the offensive
            # zone and back in, which would require resetting the counter
            if coord.x >= OFF_ZONE_X:
                num_timesteps_in_ozone += 1
            else:
                num_timesteps_in_ozone = 0
                num_timesteps_beyond_goal_line = 0
        
        # check if the goal met the criteria
        if ((coord.x - min_x_coord.x) > MIN_X_DIST) and (num_timesteps_in_ozone <= OFF_ZONE_MAX_TIMESTEPS) and\
            (num_timesteps_beyond_goal_line <= PAST_GOAL_LINE_MAX_TIMESTEPS):
            game_ids.append(goal_coords.game_id)
            goal_ids.append(goal_coords.goal_id)
            x_dists.append(coord.x - min_x_coord.x)
            off_zone_times.append(num_timesteps_in_ozone)
            beyond_goal_line_times.append(num_timesteps_beyond_goal_line)
            ppt_url.append(f'https://www.nhl.com/ppt-replay/goal/{goal_coords.game_id}/{goal_coords.goal_id}')
            
    df_rush_goals = pl.DataFrame({
        'game_ids': game_ids,
        'goal_ids': goal_ids,
        'x_dists': x_dists,
        'off_zone_times': off_zone_times,
        'beyond_goal_line_times': beyond_goal_line_times,
        'url': ppt_url
    })
    return df_rush_goals

    
if __name__ == '__main__':
    EXPORT_FILE_PATH = '2025_2026_rush_goals.parquet'

    # read in and parse the combined location and empty-net data
    df_pp_loc_eng = pl.read_parquet('2025_2026_coords_eng.csv')

    df_pp_loc_no_eng = df_pp_loc_eng.filter(
        ~pl.col('is_eng')
    )
    dict_goal_pp_loc = import_pp_data(df_pp_loc_no_eng)

    # find the rush goals and export the results
    df_rush_goals = find_rush_goals(dict_goal_pp_loc=dict_goal_pp_loc)
    df_rush_goals.write_csv(EXPORT_FILE_PATH)