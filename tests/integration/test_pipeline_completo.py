"""
test_pipeline_completo.py
Testes de integracao end-to-end.
Ingestao -> Materializacao -> Serving -> Training Dataset.
Cada teste conta uma historia completa de uso real.
"""
import pytest
from fastapi.testclient import TestClient

from src.registry.registry import FeatureRegistry
from src.store.offline_store import OfflineStore
from src.store.online_store import OnlineStore
from src.ingest.ingestor import Ingestor, IngestEvent
from src.materializer.materializer import Materializer
from src.serving.serving import create_app


@pytest.fixture
def registry():
    return FeatureRegistry(config_path="config/features.yaml")


@pytest.fixture
def offline(tmp_path):
    s = OfflineStore(store_path=str(tmp_path / "offline"))
    yield s
    s.clear()


@pytest.fixture
def online():
    s = OnlineStore()
    yield s
    s.flush()


@pytest.fixture
def ingestor(registry, offline, online):
    return Ingestor(
        registry=registry,
        offline_store=offline,
        online_store=online,
    )


@pytest.fixture
def materializer(offline, online):
    return Materializer(
        offline_store=offline,
        online_store=online,
    )


@pytest.fixture
def client(online, offline, registry):
    app = create_app(
        online_store=online,
        offline_store=offline,
        registry=registry,
    )
    return TestClient(app)


# ── pipeline completo ─────────────────────────────────────────

class TestPipelineCompleto:

    def test_ingestao_e_serving_online(
        self, ingestor, client
    ):
        """
        Historia: ingerir uma feature e servir via API.
        Caminho: IngestEvent -> OfflineStore + OnlineStore -> GET /features
        """
        ingestor.ingest(IngestEvent(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=3,
            feature_ts="2024-01-15T00:00:00",
        ))

        resp = client.get(
            "/features/customer_001",
            params={"features": ["support__open_tickets"]},
        )
        assert resp.status_code == 200
        assert resp.json()["features"]["support__open_tickets"] == 3

    def test_materializacao_restaura_online_store(
        self, ingestor, materializer, online, client
    ):
        """
        Historia: online store perdeu os dados (restart).
        Materializacao deve restaurar tudo a partir do offline store.
        """
        ingestor.ingest(IngestEvent(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=5,
            feature_ts="2024-01-15T00:00:00",
        ))

        # simula restart — online store perde os dados
        online.flush()
        assert online.get("customer_001", "support", "open_tickets") is None

        # materializacao restaura
        result = materializer.materialize_all()
        assert result.success is True
        assert result.features_materialized == 1

        # serving funciona de novo
        resp = client.get(
            "/features/customer_001",
            params={"features": ["support__open_tickets"]},
        )
        assert resp.json()["features"]["support__open_tickets"] == 5

    def test_ciclo_completo_sem_data_leakage(
        self, ingestor, client
    ):
        """
        TESTE CENTRAL DA INTEGRACAO.
        Historia do customer_002 que vai churnar em marco.

        Ingestao: 3 snapshots de open_tickets ao longo do tempo.
        Label de treino: fevereiro (antes do churn).
        Esperado: dataset retorna valor de janeiro (1),
                  nao o valor de marco (9).
        Retornar 9 seria data leakage — o modelo aprenderia
        do futuro e falharia em producao.
        """
        # ingere historico do cliente que vai churnar
        for value, ts in [
            (1, "2024-01-15T00:00:00"),   # janeiro: 1 ticket
            (4, "2024-02-10T00:00:00"),   # fevereiro: 4 tickets
            (9, "2024-03-01T00:00:00"),   # marco: 9 tickets (apos churn)
        ]:
            ingestor.ingest(IngestEvent(
                entity_id="customer_002",
                feature_group="support",
                feature_name="open_tickets",
                feature_value=value,
                feature_ts=ts,
            ))

        # gera dataset com label de fevereiro
        resp = client.post("/training-dataset", json={
            "labels": [
                {
                    "entity_id": "customer_002",
                    "label_ts":  "2024-02-01T00:00:00",
                },
            ],
            "feature_groups": ["support"],
            "feature_names":  ["open_tickets"],
        })

        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert len(rows) == 1

        valor_no_dataset = rows[0]["support__open_tickets"]
        assert valor_no_dataset == 1,   (
            f"Esperado 1 (janeiro), obtido {valor_no_dataset}"
        )
        assert valor_no_dataset != 9, (
            "DATA LEAKAGE: dataset retornou valor de marco "
            "para label de fevereiro"
        )
        assert valor_no_dataset != 4, (
            "retornou valor de fevereiro-10 para label de fevereiro-01"
        )

    def test_ingestao_invalida_nao_contamina_serving(
        self, ingestor, client
    ):
        """
        Dado invalido rejeitado pelo Ingestor
        nao deve aparecer no serving.
        """
        # ingere dado valido
        ingestor.ingest(IngestEvent(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=2,
            feature_ts="2024-01-01T00:00:00",
        ))

        # tenta ingerir dado invalido
        result = ingestor.ingest(IngestEvent(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=-99,   # invalido: abaixo do minimo
            feature_ts="2024-02-01T00:00:00",
        ))
        assert result.success is False

        # serving deve retornar o valor valido anterior
        resp = client.get(
            "/features/customer_001",
            params={"features": ["support__open_tickets"]},
        )
        assert resp.json()["features"]["support__open_tickets"] == 2

    def test_pipeline_com_scenarios_yaml(
        self, ingestor, materializer, client
    ):
        """
        Ingere todos os cenarios do scenarios.yaml.
        Materializa e verifica que a API serve os 4 clientes.
        """
        results = ingestor.ingest_from_scenarios("config/scenarios.yaml")
        sucessos = [r for r in results if r.success]
        assert len(sucessos) > 0

        # materializa para garantir online store atualizado
        mat_result = materializer.materialize_all()
        assert mat_result.success is True

        # verifica que os 4 clientes estao disponiveis
        for entity_id in [
            "customer_001", "customer_002",
            "customer_003", "customer_004"
        ]:
            resp = client.get(
                f"/features/{entity_id}",
                params={"features": ["support__open_tickets"]},
            )
            assert resp.status_code == 200

    def test_health_reflete_estado_real(
        self, ingestor, client
    ):
        """
        Health check deve refletir o estado real do online store
        antes e depois da ingestao.
        """
        resp_antes = client.get("/health")
        assert resp_antes.json()["online_store_size"] == 0

        ingestor.ingest(IngestEvent(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=3,
            feature_ts="2024-01-01T00:00:00",
        ))

        resp_depois = client.get("/health")
        assert resp_depois.json()["online_store_size"] == 1
