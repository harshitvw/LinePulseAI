"""Leakage-aware degradation-likelihood model training.

The workbook contains scenario annotations, not observed future failures.  The
model therefore detects patterns resembling the workbook's seeded degradation
scenarios.  Its output is deliberately named ``degradation_likelihood`` and is
not presented as a calibrated probability of real equipment failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from .data import DataBundle, MODEL_FEATURES


RANDOM_SEED = 20260909
DEFAULT_ARTIFACT_PATH = Path(__file__).resolve().parents[2] / "artifacts" / "degradation_model.joblib"
SEMANTIC_LABEL = "degradation likelihood (not a real-world failure probability)"


def _xgboost_classifier(scale_pos_weight: float) -> BaseEstimator | None:
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return None
    return XGBClassifier(
        n_estimators=90,
        max_depth=3,
        learning_rate=0.045,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=2.0,
        reg_alpha=0.05,
        scale_pos_weight=float(scale_pos_weight),
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=RANDOM_SEED,
        n_jobs=1,
    )


def _estimator(scale_pos_weight: float) -> tuple[Pipeline, str, bool]:
    xgb = _xgboost_classifier(scale_pos_weight)
    if xgb is not None:
        classifier = xgb
        family = "XGBoost gradient-boosted trees"
        xgboost_available = True
    else:
        # The fallback keeps local/offline setup usable.  It is not disguised as
        # XGBoost; the selected family is exposed in readiness and model cards.
        classifier = HistGradientBoostingClassifier(
            learning_rate=0.06,
            max_iter=60,
            max_leaf_nodes=15,
            l2_regularization=1.5,
            class_weight="balanced",
            random_state=RANDOM_SEED,
        )
        family = "Histogram gradient-boosted trees (XGBoost-compatible fallback)"
        xgboost_available = False
    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("classifier", classifier),
        ]
    )
    return pipeline, family, xgboost_available


@dataclass(slots=True)
class ModelBundle:
    estimator: Any
    feature_names: list[str]
    metadata: dict[str, Any]
    training_medians: dict[str, float]

    def predict_likelihood(self, frame: pd.DataFrame) -> np.ndarray:
        """Score rows from 0 to 100 using only the declared model features."""

        prepared = pd.DataFrame(index=frame.index)
        for column in self.feature_names:
            prepared[column] = pd.to_numeric(frame.get(column), errors="coerce")
        probabilities = self.estimator.predict_proba(prepared)[:, 1]
        return np.clip(probabilities * 100.0, 0.0, 100.0)

    def driver_contributions(self, frame: pd.DataFrame, top_n: int = 3) -> list[list[dict[str, Any]]]:
        """Return local, perturbation-based model drivers without a SHAP dependency.

        Each feature is replaced with its training median in turn.  The change
        in likelihood is useful directional context, but is not presented as a
        causal or additive explanation.
        """

        prepared = pd.DataFrame(index=frame.index)
        for column in self.feature_names:
            prepared[column] = pd.to_numeric(frame.get(column), errors="coerce")
        base = self.predict_likelihood(prepared)
        # One batched prediction replaces 1,080 single-row calls for the supplied
        # fleet (45 assets × 24 features), keeping dashboard startup responsive.
        blocks: list[pd.DataFrame] = []
        for feature in self.feature_names:
            changed = prepared.copy()
            changed[feature] = self.training_medians.get(feature, np.nan)
            blocks.append(changed)
        counterfactual = self.predict_likelihood(pd.concat(blocks, ignore_index=True))
        counterfactual = counterfactual.reshape(len(self.feature_names), len(prepared)).T
        contributions = base[:, None] - counterfactual

        output: list[list[dict[str, Any]]] = []
        for row_position in range(len(prepared)):
            candidates: list[dict[str, Any]] = []
            for feature_position, feature in enumerate(self.feature_names):
                contribution = float(contributions[row_position, feature_position])
                candidates.append(
                    {
                        "feature": feature,
                        "likelihood_point_change": round(contribution, 2),
                        "direction": "raises" if contribution >= 0 else "reduces",
                    }
                )
            candidates.sort(key=lambda item: abs(item["likelihood_point_change"]), reverse=True)
            output.append(candidates[:top_n])
        return output


class PeerDeviationLikelihood(ClassifierMixin, BaseEstimator):
    """Label-free, robust analytical fallback with a predict_proba contract."""

    def __init__(self) -> None:
        self.medians_: np.ndarray | None = None
        self.scales_: np.ndarray | None = None

    def fit(self, x: pd.DataFrame, y: Any = None) -> "PeerDeviationLikelihood":
        values = np.asarray(x, dtype=float)
        self.n_features_in_ = values.shape[1]
        self.classes_ = np.asarray([0, 1])
        self.medians_ = np.nanmedian(values, axis=0)
        q75 = np.nanpercentile(values, 75, axis=0)
        q25 = np.nanpercentile(values, 25, axis=0)
        scale = (q75 - q25) / 1.349
        fallback_scale = np.nanstd(values, axis=0)
        self.scales_ = np.where(scale > 1e-9, scale, np.where(fallback_scale > 1e-9, fallback_scale, 1.0))
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        if self.medians_ is None or self.scales_ is None:
            raise RuntimeError("PeerDeviationLikelihood has not been fitted")
        values = np.asarray(x, dtype=float)
        values = np.where(np.isnan(values), self.medians_, values)
        deviation = np.abs((values - self.medians_) / self.scales_)
        top = np.sort(deviation, axis=1)[:, -min(3, deviation.shape[1]) :]
        score = np.nanmean(top, axis=1)
        likelihood = 1.0 / (1.0 + np.exp(-(score - 2.0)))
        return np.column_stack([1.0 - likelihood, likelihood])


def _analytical_fallback(x: pd.DataFrame) -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
            ("classifier", PeerDeviationLikelihood()),
        ]
    )


def _safe_float(value: float | np.floating[Any]) -> float | None:
    value = float(value)
    if not np.isfinite(value):
        return None
    return round(value, 4)


def _cv_metrics(y_true: np.ndarray, probability: np.ndarray) -> dict[str, float | None]:
    prediction = (probability >= 0.5).astype(int)
    metrics: dict[str, float | None] = {
        "balanced_accuracy": _safe_float(balanced_accuracy_score(y_true, prediction)),
        "f1": _safe_float(f1_score(y_true, prediction, zero_division=0)),
        "average_precision": _safe_float(average_precision_score(y_true, probability)),
        "brier_score": _safe_float(brier_score_loss(y_true, probability)),
    }
    metrics["roc_auc"] = (
        _safe_float(roc_auc_score(y_true, probability)) if len(np.unique(y_true)) == 2 else None
    )
    return metrics


def _global_feature_importance(
    estimator: Any,
    x: pd.DataFrame,
    y: pd.Series,
) -> list[dict[str, Any]]:
    """Calculate model-agnostic descriptive importance on the training sample."""

    try:
        result = permutation_importance(
            estimator,
            x,
            y,
            scoring="balanced_accuracy",
            n_repeats=2,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )
        values = np.maximum(result.importances_mean, 0.0)
    except (TypeError, ValueError, AttributeError):
        values = np.zeros(len(MODEL_FEATURES), dtype=float)
    denominator = float(values.sum())
    normalized = values / denominator if denominator > 0 else values
    ranked = [
        {"feature": feature, "importance": round(float(value), 5)}
        for feature, value in zip(MODEL_FEATURES, normalized, strict=True)
    ]
    ranked.sort(key=lambda item: item["importance"], reverse=True)
    return ranked


def _fallback_bundle(
    x: pd.DataFrame,
    groups: pd.Series,
    missing_sensor_rows: int,
    source_sha256: str,
    artifact_path: str | Path | None,
) -> ModelBundle:
    estimator = _analytical_fallback(x)
    estimator.fit(x)
    metadata: dict[str, Any] = {
        "model_family": "Robust peer-deviation analytical fallback",
        "xgboost_available": _xgboost_classifier(1.0) is not None,
        "semantic_label": SEMANTIC_LABEL,
        "is_failure_probability": False,
        "training_mode": "label-free analytical fallback",
        "analytical_fallback_available": True,
        "target_definition": "ScenarioFlag unavailable or contains one class; no hint target used",
        "target_is_synthetic_scenario_annotation": False,
        "validation_strategy": "No label-based validation; robust peer-deviation method",
        "group_field": "AssetID not used as a feature",
        "group_leakage_detected": False,
        "fold_count": 0,
        "training_rows": int(len(x)),
        "excluded_missing_sensor_rows": int(missing_sensor_rows),
        "asset_groups": int(groups.nunique()),
        "positive_rows": 0,
        "negative_rows": int(len(x)),
        "positive_asset_groups": 0,
        "feature_names": list(MODEL_FEATURES),
        "excluded_fields": [
            "AssetID",
            "UsageID",
            "ReadingID",
            "QualityID",
            "ContextID",
            "WorkOrderID",
            "ScenarioFlag",
            "LinkedFailureMode",
            "ANSWER_KEY",
        ],
        "fold_metrics": [],
        "cross_validation": {
            "balanced_accuracy": None,
            "f1": None,
            "average_precision": None,
            "brier_score": None,
            "roc_auc": None,
        },
        "global_feature_importance": [],
        "importance_method": "not applicable in label-free fallback",
        "recommended_risk_weight": 0.0,
        "used_in_rag": False,
        "source_sha256": source_sha256,
        "source_fingerprint_sha256": source_sha256,
        "random_seed": RANDOM_SEED,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_validated": False,
        "limitation": (
            "No usable ScenarioFlag hints were available. The score is a robust "
            "peer-deviation indication and has not been validated on real failures."
        ),
    }
    bundle = ModelBundle(
        estimator=estimator,
        feature_names=list(MODEL_FEATURES),
        metadata=metadata,
        training_medians={column: float(x[column].median(skipna=True)) for column in MODEL_FEATURES},
    )
    if artifact_path is not None:
        save_model_bundle(bundle, artifact_path)
    return bundle


def train_degradation_model(
    data: DataBundle,
    artifact_path: str | Path | None = None,
) -> ModelBundle:
    """Train and group-validate the synthetic degradation detector.

    Validation groups are AssetID values.  IDs are used only to split records,
    never as predictive features.  This prevents the three weekly snapshots of
    an asset from leaking into both train and validation data.
    """

    x, y, groups = data.model_matrix()
    # Missing sensor weeks are intentionally retained for portfolio confidence,
    # but cannot have a trustworthy ScenarioFlag target.  Exclude them from
    # supervised training and report the omission in metadata.
    has_sensor_record = data.weekly["ReadingID"].notna()
    x = x.loc[has_sensor_record].reset_index(drop=True)
    y = y.loc[has_sensor_record].reset_index(drop=True)
    groups = groups.loc[has_sensor_record].reset_index(drop=True)

    if y.nunique() != 2:
        return _fallback_bundle(
            x=x,
            groups=groups,
            missing_sensor_rows=int((~has_sensor_record).sum()),
            source_sha256=data.source_sha256,
            artifact_path=artifact_path,
        )
    positive_count = int(y.sum())
    negative_count = int(len(y) - positive_count)
    scale_pos_weight = negative_count / max(positive_count, 1)

    distinct_groups = int(groups.nunique())
    positive_groups = int(groups[y.eq(1)].nunique())
    negative_groups = int(groups[y.eq(0)].nunique())
    n_splits = max(2, min(3, positive_groups, negative_groups))
    try:
        splitter = StratifiedGroupKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=RANDOM_SEED,
        )
        splits = list(splitter.split(x, y, groups))
        validation_strategy = "StratifiedGroupKFold by AssetID"
    except (TypeError, ValueError):
        splitter = GroupKFold(n_splits=n_splits)
        splits = list(splitter.split(x, y, groups))
        validation_strategy = "GroupKFold by AssetID"

    out_of_fold = np.full(len(x), np.nan, dtype=float)
    fold_metrics: list[dict[str, Any]] = []
    group_leakage_detected = False
    family = ""
    xgboost_available = False

    for fold_number, (train_idx, validation_idx) in enumerate(splits, start=1):
        train_groups = set(groups.iloc[train_idx])
        validation_groups = set(groups.iloc[validation_idx])
        overlap = sorted(train_groups & validation_groups)
        group_leakage_detected = group_leakage_detected or bool(overlap)

        estimator, family, xgboost_available = _estimator(scale_pos_weight)
        estimator.fit(x.iloc[train_idx], y.iloc[train_idx])
        fold_probability = estimator.predict_proba(x.iloc[validation_idx])[:, 1]
        out_of_fold[validation_idx] = fold_probability
        fold_result: dict[str, Any] = {
            "fold": fold_number,
            "training_rows": int(len(train_idx)),
            "validation_rows": int(len(validation_idx)),
            "training_groups": int(len(train_groups)),
            "validation_groups": int(len(validation_groups)),
            "overlapping_groups": overlap,
        }
        fold_result.update(_cv_metrics(y.iloc[validation_idx].to_numpy(), fold_probability))
        fold_metrics.append(fold_result)

    valid_oof = np.isfinite(out_of_fold)
    overall_metrics = _cv_metrics(y.to_numpy()[valid_oof], out_of_fold[valid_oof])

    estimator, family, xgboost_available = _estimator(scale_pos_weight)
    estimator.fit(x, y)
    global_importance = _global_feature_importance(estimator, x, y)
    metadata: dict[str, Any] = {
        "model_family": family,
        "xgboost_available": xgboost_available,
        "semantic_label": SEMANTIC_LABEL,
        "is_failure_probability": False,
        "training_mode": "hint-trained auxiliary classifier",
        "analytical_fallback_available": True,
        "target_definition": "1 when ScenarioFlag hint is present; 0 otherwise",
        "target_is_synthetic_scenario_annotation": True,
        "validation_strategy": validation_strategy,
        "group_field": "AssetID (split only, never a feature)",
        "group_leakage_detected": group_leakage_detected,
        "fold_count": int(len(splits)),
        "training_rows": int(len(x)),
        "excluded_missing_sensor_rows": int((~has_sensor_record).sum()),
        "asset_groups": distinct_groups,
        "positive_rows": positive_count,
        "negative_rows": negative_count,
        "positive_asset_groups": positive_groups,
        "feature_names": list(MODEL_FEATURES),
        "excluded_fields": [
            "AssetID",
            "UsageID",
            "ReadingID",
            "QualityID",
            "ContextID",
            "WorkOrderID",
            "ScenarioFlag",
            "LinkedFailureMode",
            "ANSWER_KEY",
        ],
        "fold_metrics": fold_metrics,
        "cross_validation": overall_metrics,
        "global_feature_importance": global_importance,
        "importance_method": "permutation importance on the synthetic training sample",
        "recommended_risk_weight": 0.0,
        "used_in_rag": False,
        "source_sha256": data.source_sha256,
        "source_fingerprint_sha256": data.source_sha256,
        "random_seed": RANDOM_SEED,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_validated": False,
        "limitation": (
            "Validated only against synthetic scenario annotations. Metrics do not "
            "estimate performance on real plant failures."
        ),
    }
    bundle = ModelBundle(
        estimator=estimator,
        feature_names=list(MODEL_FEATURES),
        metadata=metadata,
        training_medians={column: float(x[column].median(skipna=True)) for column in MODEL_FEATURES},
    )
    if artifact_path is not None:
        save_model_bundle(bundle, artifact_path)
    return bundle


def save_model_bundle(bundle: ModelBundle, path: str | Path = DEFAULT_ARTIFACT_PATH) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, target)
    return target


def load_model_bundle(path: str | Path = DEFAULT_ARTIFACT_PATH) -> ModelBundle:
    source = Path(path).expanduser().resolve()
    loaded = joblib.load(source)
    if not isinstance(loaded, ModelBundle):
        raise TypeError(f"Unexpected model artifact type: {type(loaded)!r}")
    return loaded


def load_or_train_model(
    data: DataBundle,
    artifact_path: str | Path = DEFAULT_ARTIFACT_PATH,
) -> ModelBundle:
    path = Path(artifact_path)
    if path.exists():
        try:
            loaded = load_model_bundle(path)
            artifact_fingerprint = loaded.metadata.get(
                "source_fingerprint_sha256",
                loaded.metadata.get("source_sha256"),
            )
            same_source = artifact_fingerprint == data.source_sha256
            xgboost_now_available = _xgboost_classifier(1.0) is not None
            best_available_family = not (
                xgboost_now_available
                and not bool(loaded.metadata.get("xgboost_available", False))
            )
            if (
                loaded.feature_names == list(MODEL_FEATURES)
                and same_source
                and best_available_family
            ):
                loaded.metadata = {**loaded.metadata, "loaded_from_artifact": True}
                return loaded
        except (OSError, TypeError, ValueError, EOFError):
            pass
    trained = train_degradation_model(data, artifact_path=path)
    trained.metadata = {**trained.metadata, "loaded_from_artifact": False}
    return trained
