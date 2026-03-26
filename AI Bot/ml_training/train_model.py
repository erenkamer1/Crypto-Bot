"""
Model training — AI Bot 4
XGBoost signal classifier.

v2: chronological split, shadow sample_weight, RandomizedSearchCV,
threshold tuning, scale_pos_weight, early stopping, regularization,
extended model_meta.json.
"""

import os
import sys
import json
import joblib
import warnings
import numpy as np
from datetime import datetime

# Avoid UnicodeEncodeError on Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Silence deprecated xgboost warnings
warnings.filterwarnings('ignore', category=UserWarning, module='xgboost')

# xgboost + sklearn
try:
    import xgboost as xgb
    from sklearn.model_selection import (
        cross_val_score, StratifiedKFold, RandomizedSearchCV
    )
    from sklearn.metrics import (
        classification_report, confusion_matrix, roc_auc_score,
        precision_recall_curve, f1_score, precision_score, recall_score
    )
    from scipy.stats import uniform, randint
except ImportError as e:
    print(f"Missing dependencies: {e}")
    print("   pip install xgboost scikit-learn scipy")
    sys.exit(1)

# Local imports
from feature_engineering import (
    load_training_data,
    prepare_features,
    create_train_test_split,
    scale_features,
    compute_sample_weights
)


def calculate_scale_pos_weight(y):
    """XGBoost scale_pos_weight = n_negative / n_positive."""
    n_positive = (y == 1).sum()
    n_negative = (y == 0).sum()
    if n_positive == 0:
        return 1.0
    ratio = n_negative / n_positive
    print(f"\nClass balance:")
    print(f"   Positive: {n_positive}")
    print(f"   Negative: {n_negative}")
    print(f"   scale_pos_weight: {ratio:.2f}")
    return ratio


def optimize_threshold(y_true, y_pred_proba, min_thresh=0.35, max_thresh=0.85, step=0.01):
    """
    Grid search threshold by max F1 on validation probabilities.

    Returns:
        best_threshold, list of per-threshold result dicts
    """
    print(f"\nThreshold search ({min_thresh:.2f} - {max_thresh:.2f})...\n")
    
    thresholds = np.arange(min_thresh, max_thresh + step, step)
    results = []
    
    for thresh in thresholds:
        y_pred = (y_pred_proba >= thresh).astype(int)
        
        # Skip degenerate all-0 or all-1 predictions
        if y_pred.sum() == 0 or y_pred.sum() == len(y_pred):
            continue
        
        f1 = f1_score(y_true, y_pred, zero_division=0)
        prec = precision_score(y_true, y_pred, zero_division=0)
        rec = recall_score(y_true, y_pred, zero_division=0)
        
        selected = y_pred.sum()
        correct = ((y_pred == 1) & (y_true == 1)).sum()
        win_rate = correct / selected * 100 if selected > 0 else 0
        accept_rate = selected / len(y_true) * 100
        
        results.append({
            'threshold': round(float(thresh), 2),
            'f1': round(float(f1), 4),
            'precision': round(float(prec), 4),
            'recall': round(float(rec), 4),
            'win_rate': round(float(win_rate), 1),
            'accept_rate': round(float(accept_rate), 1),
            'selected': int(selected),
            'total': int(len(y_true))
        })
    
    if not results:
        print("   Threshold search failed; using default 0.55.")
        return 0.55, []
    
    best = max(results, key=lambda x: x['f1'])

    sorted_results = sorted(results, key=lambda x: x['f1'], reverse=True)[:5]
    print(f"   {'Threshold':>10} {'F1':>8} {'Precision':>10} {'Recall':>8} {'WinRate':>8} {'Accept%':>8}")
    print(f"   {'-'*54}")
    for r in sorted_results:
        marker = " ◄ BEST" if r['threshold'] == best['threshold'] else ""
        print(f"   {r['threshold']:>10.2f} {r['f1']:>8.4f} {r['precision']:>10.4f} "
              f"{r['recall']:>8.4f} {r['win_rate']:>7.1f}% {r['accept_rate']:>7.1f}%{marker}")
    
    print(f"\n   Optimal threshold: {best['threshold']} (F1={best['f1']:.4f}, WinRate={best['win_rate']:.1f}%)")
    
    return best['threshold'], results


def hyperparameter_search(X_train, y_train, sample_weight=None, scale_pos_weight=1.0, n_iter=30, cv=3):
    """
    RandomizedSearchCV for XGBoost hyperparameters (AUC scoring).

    Returns:
        best_params, best_cv_auc
    """
    print(f"\nHyperparameter search (n_iter={n_iter}, cv={cv})...\n")
    
    param_distributions = {
        'max_depth': [3, 4, 5],
        'learning_rate': [0.01, 0.05, 0.1],
        'n_estimators': [100, 150, 200, 300],
        'subsample': [0.6, 0.7, 0.8, 0.9],
        'colsample_bytree': [0.6, 0.7, 0.8],
        'min_child_weight': [3, 5, 7],
        'gamma': [0.1, 0.2, 0.3],
        'reg_alpha': [0, 0.1, 0.5, 1.0],
        'reg_lambda': [1.0, 2.0, 5.0],
    }
    
    base_model = xgb.XGBClassifier(
        objective='binary:logistic',
        eval_metric='auc',
        scale_pos_weight=scale_pos_weight,
        random_state=42,
    )
    
    cv_strategy = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
    
    search = RandomizedSearchCV(
        estimator=base_model,
        param_distributions=param_distributions,
        n_iter=n_iter,
        scoring='roc_auc',
        cv=cv_strategy,
        random_state=42,
        verbose=0,
        n_jobs=-1
    )
    
    if sample_weight is not None:
        search.fit(X_train, y_train, sample_weight=sample_weight)
    else:
        search.fit(X_train, y_train)
    
    best_params = search.best_params_
    best_score = search.best_score_
    
    print(f"   Best CV AUC: {best_score:.4f}")
    print(f"   Best params:")
    for k, v in sorted(best_params.items()):
        print(f"      {k}: {v}")
    
    return best_params, best_score


def train_xgboost_model(X_train, y_train, X_test, y_test,
                         params=None, sample_weight_train=None,
                         scale_pos_weight=1.0):
    """
    Train XGBClassifier with early stopping on eval_set=(X_test, y_test).

    Returns:
        model, metrics dict, y_pred_proba on test
    """
    print("\nXGBoost training...\n")
    
    default_params = {
        'objective': 'binary:logistic',
        'eval_metric': 'auc',
        'max_depth': 4,
        'learning_rate': 0.05,
        'n_estimators': 500,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 5,
        'gamma': 0.1,
        'reg_alpha': 0.1,
        'reg_lambda': 2.0,
        'random_state': 42,
        'scale_pos_weight': scale_pos_weight,
        'early_stopping_rounds': 15,
    }

    if params:
        default_params.update(params)

    if 'n_estimators' in default_params and default_params['n_estimators'] < 500:
        default_params['n_estimators'] = 500
    
    model = xgb.XGBClassifier(**default_params)
    
    fit_kwargs = {
        'eval_set': [(X_test, y_test)],
        'verbose': False,
    }
    if sample_weight_train is not None:
        fit_kwargs['sample_weight'] = sample_weight_train
    
    model.fit(X_train, y_train, **fit_kwargs)
    
    best_iteration = getattr(model, 'best_iteration', None)
    if best_iteration is not None:
        print(f"   Early stopping at iteration {best_iteration} (max {default_params['n_estimators']})")
    
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    
    y_train_pred_proba = model.predict_proba(X_train)[:, 1]
    train_auc = roc_auc_score(y_train, y_train_pred_proba)
    
    print("Model metrics:\n")
    print(classification_report(y_test, y_pred, target_names=['Loss', 'Win']))
    
    cm = confusion_matrix(y_test, y_pred)
    print(f"\nConfusion matrix:")
    print(f"   {'':>10} {'Pred loss':>12} {'Pred win':>12}")
    print(f"   {'True loss':>10} {cm[0][0]:>12} {cm[0][1]:>12}")
    print(f"   {'True win':>10} {cm[1][0]:>12} {cm[1][1]:>12}")
    
    auc = roc_auc_score(y_test, y_pred_proba)
    print(f"\nROC-AUC: {auc:.4f}")
    print(f"   Train AUC: {train_auc:.4f} (gap: {train_auc - auc:.4f})")
    if train_auc - auc > 0.10:
        print(f"   Possible overfitting: train-test AUC gap > 0.10")
    
    total_trades = len(y_test)
    model_selected = int(y_pred.sum())
    correct_profitable = int(((y_pred == 1) & (y_test == 1)).sum())
    
    if model_selected > 0:
        model_win_rate = correct_profitable / model_selected * 100
    else:
        model_win_rate = 0
    
    baseline_win_rate = y_test.mean() * 100
    
    f1 = f1_score(y_test, y_pred, zero_division=0)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    
    print(f"\nTrading metrics:")
    print(f"   Baseline win rate: {baseline_win_rate:.1f}%")
    print(f"   Model win rate: {model_win_rate:.1f}%")
    print(f"   Trades selected: {model_selected}/{total_trades}")
    print(f"   Delta vs baseline: +{model_win_rate - baseline_win_rate:.1f}%")
    print(f"   F1: {f1:.4f} | Precision: {prec:.4f} | Recall: {rec:.4f}")
    
    metrics = {
        'auc': round(float(auc), 4),
        'train_auc': round(float(train_auc), 4),
        'baseline_win_rate': round(float(baseline_win_rate), 1),
        'model_win_rate': round(float(model_win_rate), 1),
        'model_selected_trades': model_selected,
        'total_trades': total_trades,
        'f1': round(float(f1), 4),
        'precision': round(float(prec), 4),
        'recall': round(float(rec), 4),
    }
    
    return model, metrics, y_pred_proba


def cross_validate_model(X, y, params=None, scale_pos_weight=1.0, cv=5):
    """Stratified K-fold ROC-AUC on training matrix."""
    print(f"\n{cv}-fold cross-validation...\n")
    
    model_params = {
        'objective': 'binary:logistic',
        'max_depth': 4,
        'learning_rate': 0.05,
        'n_estimators': 150,
        'random_state': 42,
        'eval_metric': 'logloss',
        'scale_pos_weight': scale_pos_weight,
    }
    if params:
        model_params.update(params)
    model_params['eval_metric'] = 'logloss'
    
    model = xgb.XGBClassifier(**model_params)
    
    cv_strategy = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
    scores = cross_val_score(model, X, y, cv=cv_strategy, scoring='roc_auc')
    
    print(f"   CV Scores: {scores}")
    print(f"   Mean AUC: {scores.mean():.4f} (+/- {scores.std() * 2:.4f})")
    
    return scores


def get_feature_importance(model, feature_names, top_n=15):
    """Print and return top-N gain importances."""
    importance = model.feature_importances_
    indices = np.argsort(importance)[::-1][:top_n]
    
    print(f"\nTop {top_n} features:")
    for i, idx in enumerate(indices):
        print(f"   {i+1}. {feature_names[idx]}: {importance[idx]:.4f}")
    
    return {feature_names[idx]: float(importance[idx]) for idx in indices}


def save_model(model, scaler, feature_names, metrics=None, 
               best_params=None, data_summary=None, optimal_threshold=None,
               feature_importance=None, cv_mean_auc=None,
               output_dir='../models'):
    """Persist model, scaler, and model_meta.json (metrics, hyperparams, etc.)."""
    os.makedirs(output_dir, exist_ok=True)
    
    model_path = os.path.join(output_dir, 'signal_classifier.pkl')
    scaler_path = os.path.join(output_dir, 'feature_scaler.pkl')
    meta_path = os.path.join(output_dir, 'model_meta.json')
    
    joblib.dump(model, model_path)
    print(f"\nModel saved: {model_path}")
    
    joblib.dump(scaler, scaler_path)
    print(f"Scaler saved: {scaler_path}")
    
    meta = {
        'version': '2.0',
        'model_type': 'XGBClassifier',
        'trained_at': datetime.now().isoformat(),
        'feature_names': feature_names,
        'use_stacking': 'meta_ai1_conf' in (feature_names or []),
    }
    
    if optimal_threshold is not None:
        meta['optimal_threshold'] = optimal_threshold
    
    if data_summary is not None:
        meta['data_summary'] = data_summary
    
    if metrics is not None:
        meta_metrics = dict(metrics)
        if cv_mean_auc is not None:
            meta_metrics['cv_mean_auc'] = round(float(cv_mean_auc), 4)
        if optimal_threshold is not None:
            meta_metrics['optimal_threshold'] = optimal_threshold
        meta['metrics'] = meta_metrics
    
    if best_params is not None:
        meta['hyperparams'] = {k: int(v) if isinstance(v, (np.integer,)) else 
                                  float(v) if isinstance(v, (np.floating,)) else v 
                               for k, v in best_params.items()}
    
    if feature_importance is not None:
        sorted_fi = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
        meta['feature_importance_top10'] = {k: round(v, 4) for k, v in sorted_fi}
    
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Meta saved: {meta_path}")


def main():
    """Train pipeline: bot1 data + optional Bot4 JSONLs."""
    print("=" * 60)
    print("AI Bot 4 - ML training")
    print("=" * 60)

    project_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..'
    ))
    bot_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..'
    ))

    main_training = os.path.join(project_root, 'bot1', 'ml_training_data.jsonl')
    own_training = os.path.join(bot_root, 'ml_training_data.jsonl')
    own_predictions = os.path.join(bot_root, 'ml_predictions.jsonl')
    extra_paths = [own_training] if os.path.exists(own_training) else []

    print(f"\nData sources:")
    print(f"   Main (bot1): {main_training} {'OK' if os.path.exists(main_training) else 'MISSING'}")
    print(f"   Bot4 extra: {own_training} {'OK' if os.path.exists(own_training) else 'MISSING'}")
    print(f"   Predictions: {own_predictions} {'OK' if os.path.exists(own_predictions) else 'MISSING'}")

    data = load_training_data(
        filepath=main_training,
        predictions_path=own_predictions,
        extra_training_paths=extra_paths if extra_paths else None,
        extra_predictions_paths=None
    )
    
    if len(data) < 50:
        print("Not enough data — need at least 50 samples.")
        return
    
    X, y, feature_names, df = prepare_features(data, use_binary_labels=True)

    sample_weights = compute_sample_weights(df)

    X_train, X_test, y_train, y_test = create_train_test_split(
        X, y, df=df, use_chronological=True
    )
    
    split_idx = int(len(X) * 0.8)
    sample_weight_train = sample_weights[:split_idx]

    X_train_scaled, X_test_scaled, scaler = scale_features(X_train, X_test)

    spw = calculate_scale_pos_weight(y_train)

    best_params, best_cv_score = hyperparameter_search(
        X_train_scaled, y_train,
        sample_weight=sample_weight_train,
        scale_pos_weight=spw,
        n_iter=30,
        cv=3
    )
    
    cv_scores = cross_validate_model(
        X_train_scaled, y_train,
        params=best_params,
        scale_pos_weight=spw,
        cv=5
    )
    
    model, metrics, y_pred_proba = train_xgboost_model(
        X_train_scaled, y_train,
        X_test_scaled, y_test,
        params=best_params,
        sample_weight_train=sample_weight_train,
        scale_pos_weight=spw
    )
    
    optimal_threshold, threshold_results = optimize_threshold(
        y_test, y_pred_proba,
        min_thresh=0.35, max_thresh=0.85, step=0.01
    )
    
    importance = get_feature_importance(model, feature_names)

    shadow_count = int((df['_source_type'] != 'real_trade').sum()) if '_source_type' in df.columns else 0
    data_summary = {
        'total_samples': int(len(X)),
        'train_samples': int(len(X_train)),
        'test_samples': int(len(X_test)),
        'positive_ratio': round(float(y.mean()), 4),
        'train_positive_ratio': round(float(y_train.mean()), 4),
        'test_positive_ratio': round(float(y_test.mean()), 4),
        'shadow_samples': shadow_count,
        'feature_count': len(feature_names),
    }
    
    train_pos = y_train.mean()
    test_pos = y_test.mean()
    if abs(train_pos - test_pos) > 0.20:
        print(f"\nLabel shift warning:")
        print(f"   Train positive: {train_pos*100:.1f}% vs test positive: {test_pos*100:.1f}%")
        print(f"   Market regime may have changed; interpret metrics accordingly.")
    
    save_model(
        model, scaler, feature_names,
        metrics=metrics,
        best_params=best_params,
        data_summary=data_summary,
        optimal_threshold=optimal_threshold,
        feature_importance=importance,
        cv_mean_auc=cv_scores.mean()
    )
    
    print("\n" + "=" * 60)
    print("AI Bot 4 training complete.")
    print(f"   Test AUC: {metrics['auc']:.4f}")
    print(f"   Optimal threshold: {optimal_threshold}")
    print(f"   Model win rate: {metrics['model_win_rate']:.1f}%")
    print(f"   Output: AI Bot 4/models/")
    print("=" * 60)
    
    return model, scaler, metrics


if __name__ == '__main__':
    main()
