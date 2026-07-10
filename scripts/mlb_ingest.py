import statsapi
import json
import logging
from datetime import datetime
from scripts.db import get_engine
from sqlalchemy import text

# configure logging
logging.basicConfig(
    filename = 'logs/pipeline.log', 
    level = logging.INFO, 
    format = '%(asctime)s - %(levelname)s - %(message)s'
)

def fetch_schedule(season: int):
    """
    Pull full season schedule and insert raw game records into raw.raw_games.
    """

    logging.info(f"Fetching schedule for {season} season...")

    schedule = statsapi.schedule(start_date=f"{season}-01-01", end_date=f"{season}-12-31")

    engine = get_engine()
    inserted = 0

    with engine.begin() as conn: 
        for game in schedule:
            game_pk = game['game_id']
            game_date = game['game_date']

            #check if already exists to avoid duplicates
            existing = conn.execute(text(
                "select id from raw.raw_games where game_pk = :game_pk"
            ), {"game_pk": game_pk}).fetchone()
            
            if existing: 
                continue

            conn.execute(text("""
                              insert into raw.raw_games (game_pk, season, game_date, raw_json, fetched_at)
                              values (:game_pk, :season, :game_date, :raw_json, :fetched_at)
                        """), {
                            "game_pk": game_pk, 
                            "season": season, 
                            "game_date": game_date, 
                            "raw_json": json.dumps(game), 
                            "fetched_at": datetime.now()
                        })
            inserted += 1
            
    logging.info(f"Schedule fetch complete - {inserted} new games inserted for {season} season.")
    print(f"Schedule fetch complete - {inserted} new games inserted for {season}.")

def fetch_box_scores(season: int):
    """
    Pull box score for each game_pk and insert into raw.raw_box_scores.
    """
    logging.info(f"Fetching box scores for {season} season...")

    engine = get_engine()
    inserted = 0
    skipped = 0

    with engine.begin() as conn:
        game_pks = conn.execute(text(
            "select game_pk from raw.raw_games where season = :season"
        ), {"season": season}).fetchall()

    for (game_pk,) in game_pks:
        try:
            with engine.begin() as conn:
                existing = conn.execute(text(
                    "select id from raw.raw_box_scores where game_pk = :game_pk"
                ), {"game_pk": game_pk}).fetchone()
                
                if existing:
                    skipped += 1
                    continue
                
                box_score = statsapi.boxscore_data(game_pk)

                conn.execute(text("""
                                  insert into raw.raw_box_scores (game_pk, raw_json, fetched_at)
                                  values (:game_pk, :raw_json, :fetched_at)
                """), {
                    "game_pk": game_pk, 
                    "raw_json": json.dumps(box_score), 
                    "fetched_at": datetime.now()
                })
                inserted += 1
        except Exception as e:
            logging.warning(f"Failed to fetch box score for game_pk {game_pk}: {e}")
            continue

    logging.info(f"Box score fetch complete - {inserted} inserted, {skipped} skipped for {season} season.")
    print(f"Box score fetch complete - {inserted} inserted, {skipped} skipped for {season} season.")

def fetch_starting_pitchers(season: int): 
    """
    Extract starting pitcher data from raw box scores and insert into staging.starting_pitchers.
    """

    logging.info(f"Extracting starting pitchers for {season} season...")

    engine = get_engine()
    inserted = 0
    skipped = 0

    with engine.begin() as conn: 
        result = conn.execute(text(
            "select game_pk, raw_json from raw.raw_box_scores where game_pk in "
            "(select game_pk from raw.raw_games where season = :season)"
        ), {"season": season})
        box_scores = [(row[0], row[1]) for row in result]    
        
    for game_pk, raw_json in box_scores:
        try: 
            with engine.begin() as conn:
                existing = conn.execute(text(
                    "select id from staging.starting_pitchers where game_pk = :game_pk"
                ), {"game_pk": game_pk}).fetchone()

                if existing: 
                    skipped += 1
                    continue

                data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)

                home_pitchers = data.get('home', {}).get('pitchers', [])
                away_pitchers = data.get('away', {}).get('pitchers', [])

                home_pitcher_id = home_pitchers[0] if home_pitchers else None
                away_pitcher_id = away_pitchers[0] if away_pitchers else None

                home_info = data.get('home', {}).get('players', {})
                away_info = data.get('away', {}).get('players', {})

                home_pitcher_name = None
                away_pitcher_name = None

                if home_pitcher_id:
                    key = f"ID{home_pitcher_id}"
                    home_pitcher_name = home_info.get(key, {}).get('person', {}).get('fullName')

                if away_pitcher_id:
                    key = f"ID{away_pitcher_id}"
                    away_pitcher_name = away_info.get(key, {}).get('person', {}).get('fullName')

                game_date = conn.execute(text(
                    "select game_date from raw.raw_games where game_pk = :game_pk"
                ), {"game_pk": game_pk}).fetchone()

                conn.execute(text("""
                                  insert into staging.starting_pitchers 
                                  (game_pk, game_date, home_pitcher_id, home_pitcher_name, 
                                  away_pitcher_id, away_pitcher_name)
                                  values (:game_pk, :game_date, :home_pitcher_id, :home_pitcher_name, 
                                  :away_pitcher_id, :away_pitcher_name)
                """), {
                    "game_pk": game_pk,
                    "game_date": game_date[0] if game_date else None,
                    "home_pitcher_id": home_pitcher_id,
                    "home_pitcher_name": home_pitcher_name,
                    "away_pitcher_id": away_pitcher_id, 
                    "away_pitcher_name": away_pitcher_name
                })
                inserted += 1

        except Exception as e:
            logging.warning(f"Failed to extract pitchers for game_pk {game_pk}: {e}")
            continue
    
    logging.info(f"Starting pitcher extraction complete - {inserted} inserted, {skipped} skipped for {season} season.")
    print(f"Starting pitcher extraction complete - {inserted} inserted, {skipped} skipped for {season} season.")
               

if __name__ == "__main__":
    fetch_schedule(2024)
    fetch_box_scores(2024)
    fetch_starting_pitchers(2024)