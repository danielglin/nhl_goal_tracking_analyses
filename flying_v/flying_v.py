import polars as pl

# import numpy as np
from scipy.spatial.distance import directed_hausdorff

from typing import List


def preprocess(df_season: pl.DataFrame) -> pl.DataFrame:
    """
    Pre-processes the tracking data by:
        - filtering out the defending team
        - removing goalie rows
        - filtering out empty-net goals

    PARAMETERS:
        - df_season (polars.DataFrame): tracking data

    RETURNS:
        - df_season_pp (polars.DataFrame): the pre-processed tracking data
    """
    # filter on just the scoring team
    df_scoring_teams = pl.read_parquet('../2025_2026_regl_season_scoring_team_ids.parquet')

    df_season_scoring = df_season.join(df_scoring_teams, on=['game_id', 'goal_id'], how='inner')
    df_season_scoring = df_season_scoring.filter(
        pl.col('team_id')==pl.col('scoring_team_id')
    )

    # remove the rows for the goalies
    df_goalies = pl.read_parquet('../2025_2026_regl_season_goalie_ids.parquet')
    s_goalies = set(df_goalies.select('goalie_id').to_series().to_list())
    df_season_pp = df_season_scoring.filter(
        ~pl.col('entity_id').is_in(s_goalies)
    )

    # need to also filter out ENG's
    df_pp_loc_eng = pl.read_parquet('../rush_goals/2025_2026_coords_eng.parquet')
    df_pp_loc_eng = df_pp_loc_eng.select([
        pl.col('game_id', 'goal_id', 'is_eng')
    ])

    df_season_pp = df_season_pp.join(df_pp_loc_eng, on=['game_id', 'goal_id']).filter(
        ~pl.col('is_eng')
    )

    return df_season_pp


def symm_hausdorff(u: List[tuple], v: List[tuple]) -> float:
    return max(directed_hausdorff(u, v)[0], directed_hausdorff(v, u)[0])


def calc_center_diff(coords: List[tuple]) -> List[tuple]:
    """
    Returns the coordinates as differences of the center
    
    PARAMETERS:
        - coords (list of 2-tuples): the coordinates of the players
        
    RETURNS:
        - l_center_diffd_coords (list of 2-tuples): the coords
            that have the center subtracted from them
    """
    # calc avg pt first
    sum_x = 0
    sum_y = 0
    for x, y in coords:
        sum_x += x
        sum_y += y

    center = (
        round(sum_x/5., 4),
        round(sum_y/5., 4)
    )
    
    # subtract the center fr each coord
    l_center_diffd_coords = []
    for x, y in coords:
        diff_x = round(x - center[0], 4)
        diff_y = round(y - center[1], 4)

        l_center_diffd_coords.append((
            diff_x,
            diff_y
        ))
    return l_center_diffd_coords


def search_timesteps_for_v(df_season_pp: pl.DataFrame) -> pl.DataFrame:
    """
    Go through timesteps of player tracking data to find the Flying V

    PARAMETERS:
        - df_season_pp (polars.DataFrame): pre-processed player tracker data
    
    RETURNS:
        - df_dists (polars.DataFrame): a df of the Hausdorf distances from
            the baseline Flying V formation
            Has the following columns:
                - game_id
                - goal_id
                - timestep
                - dist
    """
    FLYING_V_COORDS = [
        (668.9, 536.63),
        (801.6, 627.63),
        (934.3, 718.63),
        (801.6, 809.63),
        (668.9, 900.91)
    ]

    l_fv_cd = calc_center_diff(FLYING_V_COORDS)

    # build the game goal id's
    df_game_goal_ids = df_season_pp.with_columns(
        pl.concat_str(['game_id', 'goal_id'], separator='_').alias('game_goal_id')
    )
    s_game_goal_ids = set(df_game_goal_ids.select(
        pl.col('game_goal_id')
    ).to_series().to_list())

    # loop thr/ each goal
    num_done = 0
    l_game_ids = []
    l_goal_ids = []
    l_timesteps = []
    l_dists = []

    for game_goal_id in s_game_goal_ids:
        df_goal = df_game_goal_ids.filter(
            pl.col('game_goal_id')==game_goal_id
        ).sort(by='timestep')
        
        game_id, goal_id = game_goal_id.split('_')
        
        # loop thr/ each timestep
        l_goal_timesteps = list(set(df_goal.select(
            pl.col('timestep')
        ).to_series().to_list()))
        l_goal_timesteps.sort()

        for i in l_goal_timesteps:
            df_timestep = df_goal.filter(
                pl.col('timestep') == i
            )
            
            # check that there are 5 players on the ice
            if df_timestep.height != 5:
                continue
            
            xs = df_timestep.select(
                pl.col('x')
            ).to_series().to_list()
            ys = df_timestep.select(
                pl.col('y')
            ).to_series().to_list()

            # build the coords
            l_player_coords = []
            for x, y in zip(xs, ys):
                l_player_coords.append((
                    round(x, 4),
                    round(y, 4)
                ))
            
            # turn into center-diff'd rep and calc the dist
            l_altered_fv_cd = calc_center_diff(l_player_coords)
            dist = round(symm_hausdorff(l_altered_fv_cd, l_fv_cd), 4)
            
            # store info
            l_game_ids.append(game_id)
            l_goal_ids.append(goal_id)
            l_timesteps.append(i)
            l_dists.append(dist)
        
        num_done += 1
        if (num_done % 50 == 0):
            print(f'***Done w/ {num_done} out of {len(s_game_goal_ids)}')

    # build the rslt df
    df_dists = pl.DataFrame({
        'game_id': l_game_ids,
        'goal_id': l_goal_ids,
        'timestep': l_timesteps,
        'dist': l_dists
    })
    return df_dists


if __name__ == "__main__":
    df_season = pl.read_parquet('../puck_player_data_2025_2026.parquet')
    df_season_pp = preprocess(df_season)
    df_dists = search_timesteps_for_v(df_season_pp)

    # export results
    df_dists.write_parquet('flying_v_export.parquet')
