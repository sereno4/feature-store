"""
serving.py — API de serving de features para inferencia online.
Expoe o online store via HTTP.
O modelo chama esta API no momento de inferencia
e recebe o vetor de features pronto.
"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from ..store.online_store import OnlineStore
from ..store.offline_store import OfflineStore
from ..registry.registry import FeatureRegistry


class FeatureResponse(BaseModel):
    entity_id: str
    features: dict[str, Any]
    found: list[str]
    missing: list[str]


class SingleFeatureResponse(BaseModel):
    entity_id: str
    feature_group: str
    feature_name: str
    value: Optional[Any]
    found: bool


class HealthResponse(BaseModel):
    status: str
    online_store_size: int


class TrainingDatasetRequest(BaseModel):
    labels: list[dict]
    feature_groups: list[str]
    feature_names: list[str]


def create_app(
    online_store: OnlineStore,
    offline_store: OfflineStore,
    registry: FeatureRegistry,
) -> FastAPI:

    app = FastAPI(
        title="Feature Store Serving API",
        description="Serve features para inferencia online e treino.",
        version="0.1.0",
    )

    @app.get("/health", response_model=HealthResponse)
    def health():
        """Health check — usado por kubernetes liveness probe."""
        return HealthResponse(
            status="ok",
            online_store_size=online_store.count(),
        )

    @app.get("/features/{entity_id}", response_model=FeatureResponse)
    def get_features(
        entity_id: str,
        features: list[str] = Query(
            ...,
            description="Lista de features no formato group__name",
        ),
    ):
        """
        Busca multiplas features de uma entidade.
        Endpoint principal para inferencia online.

        Exemplo:
          GET /features/customer_001
            ?features=support__open_tickets
            &features=customer__plan_type
        """
        result  = {}
        found   = []
        missing = []

        for feat_key in features:
            if "__" not in feat_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"feature '{feat_key}' deve ter formato group__name",
                )
            group, name = feat_key.split("__", 1)
            value = online_store.get(entity_id, group, name)
            result[feat_key] = value
            if value is not None:
                found.append(feat_key)
            else:
                missing.append(feat_key)

        return FeatureResponse(
            entity_id=entity_id,
            features=result,
            found=found,
            missing=missing,
        )

    @app.get(
        "/features/{entity_id}/{group}/{name}",
        response_model=SingleFeatureResponse,
    )
    def get_single_feature(entity_id: str, group: str, name: str):
        """Busca uma feature especifica. Util para debug."""
        feat_def = registry.get_feature(group, name)
        if feat_def is None:
            raise HTTPException(
                status_code=404,
                detail=f"feature '{group}/{name}' nao existe no registry",
            )
        value = online_store.get(entity_id, group, name)
        return SingleFeatureResponse(
            entity_id=entity_id,
            feature_group=group,
            feature_name=name,
            value=value,
            found=value is not None,
        )

    @app.post("/training-dataset")
    def get_training_dataset(request: TrainingDatasetRequest):
        """
        Gera dataset de treino com point-in-time correctness.
        Usado pelo pipeline de treinamento — nao pela inferencia.
        """
        df = offline_store.get_training_dataset(
            labels=request.labels,
            feature_groups=request.feature_groups,
            feature_names=request.feature_names,
        )
        return {"rows": df.to_dict(orient="records")}

    return app
