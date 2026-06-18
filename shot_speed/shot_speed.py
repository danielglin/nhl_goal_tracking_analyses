from dataclasses import dataclass
from typing import List

import polars as pl

import requests
import json
import time

import math

import sys
sys.path.append('../utils')
from utils import Coord, angle, convert_api_coords, dist, find_orig_shot_defl, find_orig_shot_nondeflection, rotate_multiple_goals


def main():
    """
    Calculates the shot speed for all goals
    """
    # read in API data for goals, including shot type, location, game id, goal id
    # scoring team id, home team defending side, and home team id
    df_api_data_goals = pl.read_parquet('../lateral_puck_movement/25_26_regl_season_goal_data.parquet')

    # read in dataframe with empty net goal data
    # has columns for game id, goal id, and if a goal is empty-net or not
    df_pp_loc_eng = pl.read_parquet('../rush_goals/2025_2026_coords_eng.parquet')

    df_api_data_goals_sans_engs = df_pp_loc_eng.join(df_api_data_goals, on=['game_id', 'goal_id'])
    df_api_data_goals_sans_engs = df_api_data_goals_sans_engs.filter(
        ~pl.col('is_eng')
    )

    df_api_data_goals_converted = convert_api_coords(df_api_data_goals_sans_engs)
    df_api_data_goals_rot = rotate_multiple_goals(df_api_data_goals_converted)
    df_shot_speeds = shot_speed_df(df_api_data_goals_rot)
    df_shot_speeds = df_shot_speeds.select(
        pl.col('game_id'),
        pl.col('goal_id'),
        pl.col('is_eng'),
        pl.col('shot_type'),
        pl.col('scoring_team_id'),
        pl.col('shot_speed')
    )

    # export the result
    df_shot_speeds.write_csv('shot_speeds.csv')


def find_orig_shot_nondefl_speed(l_coords: List[tuple[float, float]], shot_x: float, shot_y: float):
    """
    Finds the original shot's location for a non-deflection goal
    
    PARAMETERS:
        - l_coords (list of tuples of 2 floats): puck tracking data
        - shot_x (float): shot x coordinate converted from API coordinates to animation coordinates
        - shot_y (float): shot y coordinate converted from API coordinates to animation coordinates
    
    RETURNS:    
        - orig_goal_backward_ind (int or None): index for the backward coordinate list
            for the original shot
            Is None if the original shot can't be found in the tracking data
        - first_backward_ind (int): index for when to start the tracking data, 
            when going backwards
    """
    DIST_DIFF_THRES = 120 # threshold for how far away a coordinate can be from the API shot location
    CHANGE_DIST_THRES_TWO = 65
    CHANGE_DIST_THRES = 40
    ANGLE_THRES = 20
    TIMESTEPS_POST_INIT_THRES = 3 # the number of steps to continue after
                                  # finding a location close enough to the API shot location

    # go thr/ goal backward
    min_dist_fr_api_shot = 99999
    orig_goal_backward_ind = None
    num_timesteps_post_init = 0

    for i, (x, y) in enumerate(l_coords[::-1]):
        if i == 0:
            continue

        dist_fr_api_shot = dist(x, y, shot_x, shot_y)


        # update info about the original shot
        prev_x = l_coords[::-1][i-1][0]
        prev_y = l_coords[::-1][i-1][1]
        curr_dist = dist(x, y, prev_x, prev_y)

        if i > 1:
            x_two_steps_before = l_coords[::-1][i-2][0]
            y_two_steps_before = l_coords[::-1][i-2][1]

            prev_dist = dist(prev_x, prev_y, x_two_steps_before, y_two_steps_before)
            dist_diff = abs(curr_dist - prev_dist)
            angle_at_prev_spot = angle(
                Coord(x=x_two_steps_before, y=y_two_steps_before),
                Coord(x=prev_x, y=prev_y),
                Coord(x=x, y=y),
            )
        else:
            dist_diff = 0
            angle_at_prev_spot = 0

        if i <= 2:
            spot_change_dist_thres = CHANGE_DIST_THRES_TWO
        else:
            spot_change_dist_thres = CHANGE_DIST_THRES
            
        # update info about the shot location
        if (dist_fr_api_shot < min_dist_fr_api_shot) and\
            (dist_fr_api_shot < DIST_DIFF_THRES) and\
            (dist_diff < spot_change_dist_thres) and\
            (angle_at_prev_spot < ANGLE_THRES):
            min_dist_fr_api_shot = dist_fr_api_shot

            # update the shot location based on the puck's tracking data
            orig_goal_backward_ind = i

        if orig_goal_backward_ind is not None:
            num_timesteps_post_init += 1

        # early return so don't have to go thr/ the rest of the tracking data
        if (num_timesteps_post_init > TIMESTEPS_POST_INIT_THRES) or\
            ((angle_at_prev_spot > ANGLE_THRES) and (min_dist_fr_api_shot < 99999)):
            return orig_goal_backward_ind
            

    return orig_goal_backward_ind


def calc_shot_speed(l_coords: list):
    """
    Calculates how long the interval is between timesteps
    
    PARAMETERS:
        - l_coords (list of (float, float) tuples): forwards coordinates of the 
            puck tracking data for just the shot
            Need to reverse in order to use w/ orig_shot_backward_ind
        
    RETURNS:
        - mph (float): speed of the original shot in MPH
    """
    FT_PER_SEC_TO_MPH_FACTOR = 3600./5280.
    ANIM_TO_FT_FACTOR = 1/12.
    ANIM_INT_TO_SEC_FACTOR = 1/0.1
    
    # need to calc the total distance traveled in feet
    total_dist_anim = 0
    num_ints = 0

    for i in range(len(l_coords)-1):
        x, y = l_coords[::-1][i]
        next_x, next_y = l_coords[::-1][i+1]
        
        total_dist_anim += dist(x, y, next_x, next_y)
        num_ints += 1
    
    total_dist_ft = total_dist_anim * ANIM_TO_FT_FACTOR
    ft_per_anim_int = total_dist_ft/num_ints
    
    # convert to Ft/sec
    ft_per_sec = ft_per_anim_int * ANIM_INT_TO_SEC_FACTOR
    
    # convert to mph
    mph = ft_per_sec * FT_PER_SEC_TO_MPH_FACTOR
    return mph


def shot_speed_df(df_goals: pl.DataFrame) -> pl.DataFrame:
    """
    Estimates the shot speed for all goals in a dataframe
    
    PARAMETERS:
        - df_goals (polars.DataFrame): dataframe with the following columns:
            - x_coordinates
            - y_coordinates
            - rot_x
            - rot_y
            - shot_type
            
    RETURNS:
        - df_shot_speed (polars.DataFrame): df_goals with an additional
            "shot_speed" column
    """
    NUM_INTERVALS = 1 # how many intervals to use when calculating the shot speed
    
    l_shot_speeds = []
    
    for row in df_goals.rows(named=True):
        x_coords = row['x_coordinates']
        y_coords = row['y_coordinates']
        shot_x = row['rot_x']
        shot_y = row['rot_y']
        shot_type = row['shot_type']
        
        l_coords = list(zip(x_coords, y_coords))
        
        # need separate logic to find backwards index of deflected shots
        try:
            if shot_type in ('deflected', 'tip-in'):
                backward_shot_ind = find_orig_shot_defl(
                    l_coords, shot_x, shot_y
                )
            else:
                backward_shot_ind = find_orig_shot_nondefl_speed(
                    l_coords, shot_x, shot_y
                )
        except Exception as e:
            print(f'Error for {row["game_id"]}, {row["goal_id"]}: {e}')
            l_shot_speeds.append(None)
            continue
        if backward_shot_ind is None:
            print(f'No shot found for {row["game_id"]}, {row["goal_id"]}')
            l_shot_speeds.append(None)
            continue

        first_ind = len(l_coords)-backward_shot_ind-1
        last_ind = len(l_coords)-backward_shot_ind+NUM_INTERVALS

        l_coords = l_coords[first_ind:last_ind]

        try:
            shot_speed = calc_shot_speed(
                l_coords
            )
        except Exception as e:
            print(f'Unable to calcuate shot speed for {row["game_id"]}, {row["goal_id"]}: {e}')
            l_shot_speeds.append(None)
            continue
        l_shot_speeds.append(shot_speed)
    
    df_shot_speed = df_goals.with_columns(
        pl.Series(values=l_shot_speeds, name='shot_speed')
    )
    return df_shot_speed


if __name__ == '__main__':
    main()