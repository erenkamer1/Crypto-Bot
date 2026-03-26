"""
Model improvement: retrain using real trade outcomes.

Usage:
    python improve_model.py --analyze     # Current performance
    python improve_model.py --merge       # Check new rows to merge
    python improve_model.py --retrain     # Retrain model
    python improve_model.py --full        # All steps
"""

import json
import os
import sys

PREDICTIONS_FILE = "ml_predictions.jsonl"
TRAINING_DATA_FILE = "ml_training_data.jsonl"
NEW_TRAINING_FILE = "ml_training_data_updated.jsonl"


def load_predictions():
    """Load ML predictions JSONL."""
    if not os.path.exists(PREDICTIONS_FILE):
        print(f"{PREDICTIONS_FILE} not found.")
        return []

    predictions = []
    with open(PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                predictions.append(json.loads(line.strip()))
            except Exception:
                continue

    print(f"Loaded {len(predictions)} predictions.")
    return predictions


def load_training_data():
    """Load existing training JSONL."""
    if not os.path.exists(TRAINING_DATA_FILE):
        print(f"{TRAINING_DATA_FILE} not found!")
        return []

    data = []
    with open(TRAINING_DATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data.append(json.loads(line.strip()))
            except Exception:
                continue

    print(f"Loaded {len(data)} training rows.")
    return data


def analyze_predictions():
    """Print performance report from ml_predictions.jsonl."""
    predictions = load_predictions()

    if not predictions:
        return

    total = len(predictions)
    accepted = [p for p in predictions if p.get('accepted', False)]
    rejected = [p for p in predictions if not p.get('accepted', False)]

    with_outcome = [p for p in predictions if p.get('outcome') is not None]

    print("\n" + "="*60)
    print("ML PREDICTION ANALYSIS")
    print("="*60)

    print(f"\nOverview:")
    print(f"   Total predictions: {total}")
    print(f"   Accepted: {len(accepted)} ({len(accepted)/total*100:.1f}%)")
    print(f"   Rejected: {len(rejected)} ({len(rejected)/total*100:.1f}%)")
    print(f"   With outcome: {len(with_outcome)}")

    if accepted:
        avg_conf_accepted = sum(p['confidence'] for p in accepted) / len(accepted)
        print(f"\n   Avg confidence (accepted): {avg_conf_accepted:.3f}")

    if rejected:
        avg_conf_rejected = sum(p['confidence'] for p in rejected) / len(rejected)
        print(f"   Avg confidence (rejected): {avg_conf_rejected:.3f}")

    if with_outcome:
        accepted_with_outcome = [p for p in with_outcome if p.get('accepted', False)]
        rejected_with_outcome = [p for p in with_outcome if not p.get('accepted', False)]

        print(f"\nOutcomes (where known):")

        if accepted_with_outcome:
            wins = sum(1 for p in accepted_with_outcome if p['outcome'] in ['win', 'full_win', 'breakeven'])
            losses = len(accepted_with_outcome) - wins
            win_rate = wins / len(accepted_with_outcome) * 100

            print(f"\n   ACCEPTED:")
            print(f"   Total: {len(accepted_with_outcome)}")
            print(f"   Wins (incl. BE): {wins} ({win_rate:.1f}%)")
            print(f"   Losses: {losses} ({100-win_rate:.1f}%)")

        if rejected_with_outcome:
            would_win = sum(1 for p in rejected_with_outcome if p['outcome'] in ['win', 'full_win', 'breakeven'])
            would_lose = len(rejected_with_outcome) - would_win

            print(f"\n   REJECTED (counterfactual):")
            print(f"   Total: {len(rejected_with_outcome)}")
            print(f"   Would have won: {would_win} ({would_win/len(rejected_with_outcome)*100:.1f}%)")
            print(f"   Would have lost: {would_lose} ({would_lose/len(rejected_with_outcome)*100:.1f}%)")

            print(f"\n   MODEL NOTE:")
            if accepted_with_outcome:
                if win_rate > 65:
                    print(f"   Strong accepted win rate: {win_rate:.1f}%")
                elif win_rate > 55:
                    print(f"   Moderate accepted win rate: {win_rate:.1f}%")
                else:
                    print(f"   Low accepted win rate — consider retrain: {win_rate:.1f}%")

                if would_lose > would_win:
                    print(f"   Rejects skew losing — good filter.")
                else:
                    print(f"   Many rejects would have won — consider lowering threshold.")

    print("\n" + "="*60)
    return with_outcome


def update_prediction_outcomes(outcomes_dict):
    """
    Bulk-update outcomes in predictions file.

    Args:
        outcomes_dict: {(symbol, timestamp): (outcome, profit_pct)}
    """
    if not os.path.exists(PREDICTIONS_FILE):
        print("Predictions file not found.")
        return

    updated_records = []
    update_count = 0

    with open(PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            record = json.loads(line.strip())
            key = (record['symbol'], record['timestamp'])

            if key in outcomes_dict:
                outcome, profit_pct = outcomes_dict[key]
                record['outcome'] = outcome
                record['profit_pct'] = profit_pct
                update_count += 1

            updated_records.append(record)

    with open(PREDICTIONS_FILE, 'w', encoding='utf-8') as f:
        for record in updated_records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    print(f"Updated {update_count} predictions.")


def merge_new_data():
    """
    Report how many prediction rows with outcomes are not yet in training set.
    """
    training_data = load_training_data()
    predictions = load_predictions()

    existing_ids = {d.get('signal_id') for d in training_data}

    new_with_outcome = [
        p for p in predictions
        if p.get('outcome') is not None
        and p.get('signal_id') not in existing_ids
    ]

    print(f"\nData status:")
    print(f"   Training rows: {len(training_data)}")
    print(f"   New predictions with outcome (not in training): {len(new_with_outcome)}")

    if new_with_outcome:
        print(f"\n   {len(new_with_outcome)} rows could be merged into training.")
        print(f"   Retrain: python improve_model.py --retrain")

    return new_with_outcome


def retrain_model():
    """Run ml_training/train_model.py."""
    print("\nStarting model retrain...\n")

    import subprocess

    result = subprocess.run(
        [sys.executable, "train_model.py"],
        cwd="ml_training",
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print(f"Stderr:\n{result.stderr}")

    if result.returncode == 0:
        print("\nRetrain finished OK.")
    else:
        print("\nRetrain failed (non-zero exit).")


def print_improvement_guide():
    """Print improvement workflow."""
    print("""
+------------------------------------------------------------------+
|              MODEL IMPROVEMENT GUIDE                             |
+------------------------------------------------------------------+
|                                                                  |
|  1) COLLECT DATA (run bot 1-2 weeks)                             |
|     ml_predictions.jsonl fills while the bot runs                |
|                                                                  |
|  2) OUTCOMES                                                       |
|     ml_data_logger.update_label() on trade close                 |
|     (automatic in normal flow)                                   |
|                                                                  |
|  3) ANALYZE: python improve_model.py --analyze                 |
|                                                                  |
|  4) RETRAIN: python improve_model.py --retrain                   |
|     Uses merged training sources (see ML_README)                 |
|                                                                  |
|  5) THRESHOLD: config / runtime — ML_CONFIDENCE_THRESHOLD      |
|     Low win rate -> raise threshold; too few signals -> lower    |
|                                                                  |
+------------------------------------------------------------------+
""")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Model improvement helper')
    parser.add_argument('--analyze', action='store_true', help='Analyze current performance')
    parser.add_argument('--merge', action='store_true', help='Check new rows for training')
    parser.add_argument('--retrain', action='store_true', help='Retrain model')
    parser.add_argument('--full', action='store_true', help='Analyze + merge + retrain')
    parser.add_argument('--guide', action='store_true', help='Show guide')

    args = parser.parse_args()

    if args.guide or (not any([args.analyze, args.merge, args.retrain, args.full])):
        print_improvement_guide()
        return

    if args.analyze or args.full:
        analyze_predictions()

    if args.merge or args.full:
        merge_new_data()

    if args.retrain or args.full:
        retrain_model()


if __name__ == '__main__':
    main()
