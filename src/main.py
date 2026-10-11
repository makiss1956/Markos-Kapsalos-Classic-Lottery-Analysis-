"""
Main Eurojackpot pipeline.
Workflow:
1. Initialize database.
2. Synchronize historical CSV (using the extended 2012-2026 dataset with Status).
3. Retrieve the latest real draw from OPAP.
4. Store the latest draw into DB (if new).
5. Evaluate the previous prediction.
6. Determine the next draw.
7. Perform classification (Roll-over vs Winner) & targeted frequency analysis.
8. Save prediction (supporting 5+2 and 3+1).
9. Send email.
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("LotteryPipeline")

from src.analytics.backtester import Backtester
from src.analytics.frequency_analyzer import FrequencyAnalyzer
from src.analytics.predictor import ProbabilityPredictor
from src.database.db_manager import DBManager
from src.importers.eurojackpot_importer import EurojackpotImporter


def run_pipeline() -> Dict[str, Any]:
    logger.info("=" * 70)
    logger.info("LOTTERY INTELLIGENCE PLATFORM - ENHANCED PIPELINE")
    logger.info("PIPELINE START")
    logger.info("=" * 70)

    # ---------------------------------------------------------
    # STEP 1
    # ---------------------------------------------------------
    logger.info("STEP 1 - Initialize database")
    db = DBManager()
    logger.info("Database draws: %d", db.get_draw_count())

    # ---------------------------------------------------------
    # STEP 2
    # ---------------------------------------------------------
    logger.info("STEP 2 - Synchronize historical CSV")
    importer = EurojackpotImporter(db_manager=db)
    inserted = importer.sync_history()
    logger.info("CSV synchronization inserted %d draws", inserted)

    # ---------------------------------------------------------
    # STEP 3 & 4 - Retrieve & Store Live Draw
    # ---------------------------------------------------------
    logger.info("STEP 3 - Retrieve latest live draw")
    latest_draw = importer.fetch_latest_draw()

    if latest_draw is None:
        logger.warning(
            "⚠ Δεν ήταν δυνατή η ανάκτηση κλήρωσης από το OPAP API. "
            "Συνεχίζουμε με την τελευταία αποθηκευμένη κλήρωση από τη βάση."
        )
        latest_draw = db.get_latest_draw()
        if latest_draw is None:
            raise RuntimeError(
                "Αποτυχία: Δεν υπάρχει καμία κλήρωση ούτε από το API ούτε από τη βάση."
            )
        logger.info(
            "✅ Χρήση τελευταίας αποθηκευμένης κλήρωσης: %s",
            latest_draw["draw_date"],
        )
    else:
        is_new = db.insert_draw(latest_draw)
        if is_new:
            logger.info("✅ Η νέα live κλήρωση (%s) αποθηκεύτηκε στη βάση.", latest_draw["draw_date"])

    latest_date = latest_draw["draw_date"]
    logger.info(
        "LATEST DRAW: %s | Main=%s | Euro=%s",
        latest_date,
        latest_draw["primary_numbers"],
        latest_draw["euro_numbers"],
    )

    # ---------------------------------------------------------
    # STEP 5 - Evaluate Previous Prediction
    # ---------------------------------------------------------
    logger.info("STEP 5 - Evaluate previous prediction")
    predictions = db.get_predictions(limit=100)
    evaluated_prediction: Optional[Dict[str, Any]] = None

    for prediction in predictions:
        if prediction.get("for_draw_date") != latest_date:
            continue
        evaluated_prediction = Backtester.evaluate_prediction(
            predicted_mains=prediction.get("predicted_primary", []),
            predicted_euros=prediction.get("predicted_euro", []),
            actual_draw=latest_draw,
        )
        logger.info("PREVIOUS PREDICTION RESULT")
        logger.info(
            "Main hits: %d / %d",
            evaluated_prediction.get("main_hits_count", 0),
            len(prediction.get("predicted_primary", []))
        )
        logger.info(
            "Joker/Euro hits: %d / %d",
            evaluated_prediction.get("euro_hits_count", 0),
            len(prediction.get("predicted_euro", []))
        )
        break

    if evaluated_prediction is None:
        logger.info("No previous prediction found for draw %s", latest_date)

    # ---------------------------------------------------------
    # STEP 6 - Determine Next Draw Date
    # ---------------------------------------------------------
    logger.info("STEP 6 - Determine next draw")
    next_draw_date = importer.get_next_draw_date()
    logger.info("NEXT DRAW TARGET: %s", next_draw_date)

    # ---------------------------------------------------------
    # STEP 7 - Advanced Roll-over / Winner Classification & Frequency Analysis
    # ---------------------------------------------------------
    logger.info("STEP 7 - Generate Prediction with Roll-over / Winner Analysis")
    
    # Διορθωμένη διαδρομή σύμφωνα με το GitHub repository σας
    csv_file_path = "data/eurojackpot_raw_history.csv"
    try:
        df_history = pd.read_csv(csv_file_path, sep=';')
        # Μετατροπή Status σε αριθμητικό (1 για JACKPOT/Roll-over, 0 για WINNER)
        df_history['Is_Jackpot'] = df_history['Status'].apply(lambda x: 1 if str(x).strip().upper() == 'JACKPOT' else 0)
        
        # Διαχωρισμός σε υποομάδες ιστορικού
        roll_over_pool = df_history[df_history['Is_Jackpot'] == 1]
        winner_pool = df_history[df_history['Is_Jackpot'] == 0]

        # Αυτόνομη πρόβλεψη κατάστασης (Pure Python) με βάση την τελευταία τιμή
        last_status_val = df_history.iloc[-1]['Is_Jackpot']
        next_status_pred = 1 if last_status_val == 1 else 0
        next_status_str = "JACKPOT (Roll-over)" if next_status_pred == 1 else "WINNER"
        logger.info("1. Εκτίμηση επόμενης κλήρωσης (Roll-over/Winner): %s", next_status_str)
        
        # Επιλογή της κατάλληλης δεξαμενής δεδομένων με βάση την πρόβλεψη κατάστασης
        target_pool = roll_over_pool if next_status_pred == 1 else winner_pool
        
        # Υπολογισμός συχνοτήτων αποκλειστικά από την επιλεγμένη ομάδα
        main_series = pd.concat([target_pool['N1'], target_pool['N2'], target_pool['N3'], target_pool['N4'], target_pool['N5']])
        euro_series = pd.concat([target_pool['E1'], target_pool['E2']])
        
        top_mains = main_series.value_counts().index.tolist()
        top_euros = euro_series.value_counts().index.tolist()
        
        # 2. Πρόβλεψη 5 + 2
        primary_candidates_5_2 = sorted(top_mains[:5])
        euro_candidates_5_2 = sorted(top_euros[:2])
        
        # 3. Πρόβλεψη 3 κύριοι αριθμοί + 1 Τζόκερ/Euro
        primary_candidates_3_1 = sorted(top_mains[:3])
        euro_candidates_3_1 = sorted(top_euros[:1])
        
        primary_candidates = primary_candidates_3_1
        joker_candidates = euro_candidates_3_1
        
    except Exception as e:
        logger.warning("⚠ Σφάλμα κατά την ανάγνωση του αρχείου ιστορικού Status: %s. Εναλλαγή σε τυπικό FrequencyAnalyzer.", e)
        frequency_analyzer = FrequencyAnalyzer(db)
        predictor = ProbabilityPredictor(frequency_analyzer=frequency_analyzer, pattern_analyzer=None)
        prediction = predictor.predict_candidate_set(primary_count=3, euro_count=1)
        primary_candidates = sorted(prediction["primary_candidates"])
        joker_candidates = sorted(prediction["euro_candidates"])
        next_status_str = "UNKNOWN"
        primary_candidates_5_2 = sorted(prediction["primary_candidates"][:5]) if len(prediction["primary_candidates"]) >= 5 else prediction["primary_candidates"]
        euro_candidates_5_2 = sorted(prediction["euro_candidates"][:2]) if len(prediction["euro_candidates"]) >= 2 else prediction["euro_candidates"]

    logger.info("NEW PREDICTION (3 + 1): Main=%s | Euro=%s", primary_candidates, joker_candidates)
    logger.info("NEW PREDICTION (5 + 2): Main=%s | Euro=%s", primary_candidates_5_2, euro_candidates_5_2)

    # ---------------------------------------------------------
    # STEP 8 - Save Prediction
    # ---------------------------------------------------------
    logger.info("STEP 8 - Save prediction")
    if db.prediction_exists(next_draw_date):
        logger.warning("Prediction already exists for %s", next_draw_date)
        existing = next(
            (
                item for item in db.get_predictions(limit=100)
                if item.get("for_draw_date") == next_draw_date
            ),
            None,
        )
        return {
            "status": "already_exists",
            "latest_draw": latest_draw,
            "evaluated_prediction": evaluated_prediction,
            "next_draw_date": next_draw_date,
            "prediction": existing,
            "email_sent": False,
        }

    saved = db.save_prediction(
        for_draw_date=next_draw_date,
        primary_numbers=primary_candidates,
        euro_numbers=joker_candidates,
        metadata={
            "method": "rollover_targeted_frequency",
            "next_status_prediction": next_status_str,
            "prediction_5_2": {"primary": primary_candidates_5_2, "euro": euro_candidates_5_2}
        },
    )
    if not saved:
        raise RuntimeError("Prediction could not be saved.")
    logger.info("Prediction saved successfully.")

    # ---------------------------------------------------------
    # STEP 9 - Email Notification
    # ---------------------------------------------------------
    logger.info("STEP 9 - Send email")
    email_sent = False
    try:
        from src.notifications.email_sender import LotteryEmailSender
        email_sender = LotteryEmailSender()
        email_prediction = {
            "for_draw_date": next_draw_date,
            "primary_candidates": primary_candidates,
            "euro_candidates": joker_candidates,
            "joker_candidates": joker_candidates,
            "method": "rollover_targeted_frequency",
            "next_status_prediction": next_status_str,
            "prediction_5_2_primary": primary_candidates_5_2,
            "prediction_5_2_euro": euro_candidates_5_2,
            "evaluation": evaluated_prediction,
        }
        email_sent = email_sender.send_prediction(
            prediction=email_prediction,
            stats={"total_draws": db.get_draw_count()},
        )
    except Exception:
        logger.exception("Email step failed.")

    # ---------------------------------------------------------
    # RESULT
    # ---------------------------------------------------------
    result = {
        "status": "success",
        "latest_draw": latest_draw,
        "evaluated_prediction": evaluated_prediction,
        "next_draw_date": next_draw_date,
        "next_draw_status_prediction": next_status_str,
        "prediction_3_1": {
            "primary_candidates": primary_candidates,
            "euro_candidates": joker_candidates,
        },
        "prediction_5_2": {
            "primary_candidates": primary_candidates_5_2,
            "euro_candidates": euro_candidates_5_2,
        },
        "prediction_saved": True,
        "email_sent": email_sent,
        "new_draws_inserted": inserted,
        "total_draws": db.get_draw_count(),
    }

    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETED SUCCESSFULLY")
    logger.info("1. Next draw status prediction: %s", next_status_str)
    logger.info("2. Prediction (5+2): Main=%s | Euro=%s", primary_candidates_5_2, euro_candidates_5_2)
    logger.info("3. Prediction (3+1): Main=%s | Euro=%s", primary_candidates, joker_candidates)
    logger.info("=" * 70)

    return result


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception:
        logger.exception("PIPELINE FAILED.")
        sys.exit(1)
