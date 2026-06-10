"""
main.py — Ponto de entrada da Feature Store.
Inicializa todos os modulos, popula os stores
e sobe a API de serving.
"""
import os
import uvicorn

from src.registry.registry import FeatureRegistry
from src.store.offline_store import OfflineStore
from src.store.online_store import OnlineStore
from src.ingest.ingestor import Ingestor
from src.materializer.materializer import Materializer
from src.serving.serving import create_app


def main():
    print("Feature Store iniciando...")

    # 1. registry
    registry = FeatureRegistry(
        config_path=os.getenv("FEATURES_CONFIG", "config/features.yaml")
    )
    print(f"  Registry: {registry.list_groups()}")

    # 2. stores
    offline = OfflineStore(
        store_path=os.getenv("OFFLINE_STORE_PATH", "data/offline")
    )
    online = OnlineStore()

    # 3. ingestor — popula com cenarios se store vazio
    if offline.count() == 0:
        print("  Offline store vazio — ingerindo scenarios.yaml...")
        ingestor = Ingestor(
            registry=registry,
            offline_store=offline,
            online_store=online,
        )
        results = ingestor.ingest_from_scenarios(
            os.getenv("SCENARIOS_PATH", "config/scenarios.yaml")
        )
        sucessos = sum(1 for r in results if r.success)
        falhas   = sum(1 for r in results if not r.success)
        print(f"  Ingestao: {sucessos} ok, {falhas} falhas")
    else:
        print(f"  Offline store: {offline.count()} eventos")

    # 4. materializer — sincroniza online store
    print("  Materializando online store...")
    materializer = Materializer(
        offline_store=offline,
        online_store=online,
    )
    result = materializer.materialize_all()
    print(
        f"  Materializacao: {result.features_materialized} features, "
        f"{len(result.entities_updated)} entidades"
    )

    # 5. API
    app = create_app(
        online_store=online,
        offline_store=offline,
        registry=registry,
    )

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    print(f"\nAPI disponivel em http://{host}:{port}")
    print(f"Documentacao em  http://{host}:{port}/docs\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
