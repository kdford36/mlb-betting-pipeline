import json
import logging
from datetime import datetime
from scripts.db import get_engine
from sqlalchemy import text

logging.basicConfig(
    filename='logs/pipeline.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def transform_games(season: int):
    """
    Flatten raw box score JSON into staging.games.
    """
    logging.info(f"Transforming games for {season} season...")

    engine = get_engine()
    inserted = 0
    skipped = 0

    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT b.game_pk, b.raw_json, g.game_date
            FROM raw.raw_box_scores b
            JOIN raw.raw_games g ON b.game_pk = g.game_pk
            WHERE g.season = :season
        """), {"season": season})
        rows = [(row[0], row[1], row[2]) for row in result]

    for game_pk, raw_json, game_date in rows:
        try:
            with engine.begin() as conn:
                existing = conn.execute(text(
                    "SELECT id FROM staging.games WHERE game_pk = :game_pk"
                ), {"game_pk": game_pk}).fetchone()

                if existing:
                    skipped += 1
                    continue

                data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)

                home = data.get('home', {})
                away = data.get('away', {})

                home_team_id = home.get('team', {}).get('id')
                home_team_name = home.get('team', {}).get('name')
                away_team_id = away.get('team', {}).get('id')
                away_team_name = away.get('team', {}).get('name')

                home_score = home.get('teamStats', {}).get('batting', {}).get('runs')
                away_score = away.get('teamStats', {}).get('batting', {}).get('runs')

                if home_score is not None and away_score is not None:
                    winner = 'home' if home_score > away_score else 'away'
                else:
                    winner = None

                venue = data.get('gameInfo', {})
                venue_name = venue.get('venue') if isinstance(venue, dict) else None

                conn.execute(text("""
                    INSERT INTO staging.games
                        (game_pk, game_date, season, home_team_id, away_team_id,
                         home_team_name, away_team_name, home_score, away_score,
                         winner, venue_name)
                    VALUES
                        (:game_pk, :game_date, :season, :home_team_id, :away_team_id,
                         :home_team_name, :away_team_name, :home_score, :away_score,
                         :winner, :venue_name)
                """), {
                    "game_pk": game_pk,
                    "game_date": game_date,
                    "season": season,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_team_name": home_team_name,
                    "away_team_name": away_team_name,
                    "home_score": home_score,
                    "away_score": away_score,
                    "winner": winner,
                    "venue_name": venue_name
                })
                inserted += 1

        except Exception as e:
            logging.warning(f"Failed to transform game_pk {game_pk}: {e}")
            continue

    logging.info(f"Game transform complete - {inserted} inserted, {skipped} skipped for {season} season.")
    print(f"Game transform complete - {inserted} inserted, {skipped} skipped for {season} season.")


def transform_player_game_log(season: int):
    """
    Flatten raw box score JSON into staging.player_game_log.
    """
    logging.info(f"Transforming player game logs for {season} season...")

    engine = get_engine()
    inserted = 0
    skipped = 0

    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT b.game_pk, b.raw_json, g.game_date
            FROM raw.raw_box_scores b
            JOIN raw.raw_games g ON b.game_pk = g.game_pk
            WHERE g.season = :season
        """), {"season": season})
        rows = [(row[0], row[1], row[2]) for row in result]

    for game_pk, raw_json, game_date in rows:
        try:
            data = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)

            team_info = data.get('teamInfo', {})
            home_team_id = team_info.get('home', {}).get('id')
            away_team_id = team_info.get('away', {}).get('id')

            batter_sets = [
                ('away', away_team_id, data.get('awayBatters', []), 'batter'),
                ('home', home_team_id, data.get('homeBatters', []), 'batter'),
            ]
            pitcher_sets = [
                ('away', away_team_id, data.get('awayPitchers', []), 'pitcher'),
                ('home', home_team_id, data.get('homePitchers', []), 'pitcher'),
            ]

            for side, team_id, player_list, player_type in batter_sets + pitcher_sets:
                for player in player_list:
                    player_id = player.get('personId')
                    if not player_id:
                        continue

                    # skip header rows
                    if player.get('battingOrder') == '' and player_type == 'batter':
                        continue
                    if player.get('namefield', '').endswith('Pitchers'):
                        continue

                    with engine.begin() as conn:
                        existing = conn.execute(text("""
                            SELECT id FROM staging.player_game_log
                            WHERE game_pk = :game_pk AND player_id = :player_id
                        """), {"game_pk": game_pk, "player_id": player_id}).fetchone()

                        if existing:
                            skipped += 1
                            continue

                        if player_type == 'batter':
                            conn.execute(text("""
                                INSERT INTO staging.player_game_log
                                    (game_pk, game_date, player_id, player_name, team_id, player_type,
                                     at_bats, hits, doubles, triples, home_runs, rbi, walks, strikeouts)
                                VALUES
                                    (:game_pk, :game_date, :player_id, :player_name, :team_id, :player_type,
                                     :at_bats, :hits, :doubles, :triples, :home_runs, :rbi, :walks, :strikeouts)
                            """), {
                                "game_pk": game_pk,
                                "game_date": game_date,
                                "player_id": player_id,
                                "player_name": player.get('name'),
                                "team_id": team_id,
                                "player_type": player_type,
                                "at_bats": int(player.get('ab', 0) or 0),
                                "hits": int(player.get('h', 0) or 0),
                                "doubles": int(player.get('doubles', 0) or 0),
                                "triples": int(player.get('triples', 0) or 0),
                                "home_runs": int(player.get('hr', 0) or 0),
                                "rbi": int(player.get('rbi', 0) or 0),
                                "walks": int(player.get('bb', 0) or 0),
                                "strikeouts": int(player.get('k', 0) or 0),
                            })
                        else:
                            conn.execute(text("""
                                INSERT INTO staging.player_game_log
                                    (game_pk, game_date, player_id, player_name, team_id, player_type,
                                     innings_pitched, hits_allowed, earned_runs, walks_allowed, pitcher_strikeouts)
                                VALUES
                                    (:game_pk, :game_date, :player_id, :player_name, :team_id, :player_type,
                                     :innings_pitched, :hits_allowed, :earned_runs, :walks_allowed, :pitcher_strikeouts)
                            """), {
                                "game_pk": game_pk,
                                "game_date": game_date,
                                "player_id": player_id,
                                "player_name": player.get('name'),
                                "team_id": team_id,
                                "player_type": player_type,
                                "innings_pitched": player.get('ip'),
                                "hits_allowed": int(player.get('h', 0) or 0),
                                "earned_runs": int(player.get('er', 0) or 0),
                                "walks_allowed": int(player.get('bb', 0) or 0),
                                "pitcher_strikeouts": int(player.get('k', 0) or 0),
                            })
                        inserted += 1

        except Exception as e:
            logging.warning(f"Failed to transform player log for game_pk {game_pk}: {e}")
            continue

    logging.info(f"Player game log transform complete - {inserted} inserted, {skipped} skipped for {season} season.")
    print(f"Player game log transform complete - {inserted} inserted, {skipped} skipped for {season} season.")

if __name__ == "__main__":
    transform_games(2024)
    transform_player_game_log(2024)