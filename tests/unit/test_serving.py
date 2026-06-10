"""
test_serving.py
Valida os endpoints da API de serving com TestClient.
Sem servidor real — testes em memoria, rapidos e isolados.
"""
import pytest
from fastapi.testclient import TestClient

from src.serving.serving import create_app
from src.store.online_store import OnlineStore
from src.store.offline_store import OfflineStore
from src.registry.registry import FeatureRegistry


@pytest.fixture
def online():
    s = OnlineStore()
    yield s
    s.flush()


@pytest.fixture
def offline(tmp_path):
    s = OfflineStore(store_path=str(tmp_path / "offline"))
    yield s
    s.clear()


@pytest.fixture
def registry():
    return FeatureRegistry(config_path="config/features.yaml")


@pytest.fixture
def client(online, offline, registry):
    app = create_app(
        online_store=online,
        offline_store=offline,
        registry=registry,
    )
    return TestClient(app)


@pytest.fixture
def client_com_dados(client, online):
    """Client com dados pre-populados no online store."""
    online.set("customer_001", "support", "open_tickets",
               3, "2024-01-15T00:00:00")
    online.set("customer_001", "customer", "plan_type",
               "premium", "2024-01-15T00:00:00")
    online.set("customer_001", "transactions", "tx_count_30d",
               45, "2024-01-15T00:00:00")
    online.set("customer_002", "support", "open_tickets",
               7, "2024-01-15T00:00:00")
    return client


# ── health ────────────────────────────────────────────────────

class TestHealth:

    def test_health_retorna_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_retorna_tamanho_do_store(self, client, online):
        online.set("c1", "support", "open_tickets", 1, "2024-01-01")
        online.set("c2", "support", "open_tickets", 2, "2024-01-01")
        resp = client.get("/health")
        assert resp.json()["online_store_size"] == 2


# ── get features ──────────────────────────────────────────────

class TestGetFeatures:

    def test_retorna_features_existentes(self, client_com_dados):
        resp = client_com_dados.get(
            "/features/customer_001",
            params={"features": [
                "support__open_tickets",
                "customer__plan_type",
            ]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == "customer_001"
        assert data["features"]["support__open_tickets"] == 3
        assert data["features"]["customer__plan_type"] == "premium"

    def test_found_e_missing_separados(self, client_com_dados):
        """
        Mistura de features existentes e ausentes.
        found e missing devem refletir o que foi encontrado.
        """
        resp = client_com_dados.get(
            "/features/customer_001",
            params={"features": [
                "support__open_tickets",       # existe
                "customer__monthly_spend_usd",  # nao existe no store
            ]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "support__open_tickets" in data["found"]
        assert "customer__monthly_spend_usd" in data["missing"]
        assert data["features"]["customer__monthly_spend_usd"] is None

    def test_entity_sem_features_retorna_tudo_missing(self, client_com_dados):
        resp = client_com_dados.get(
            "/features/nao_existe",
            params={"features": ["support__open_tickets"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["support__open_tickets"] is None
        assert "support__open_tickets" in data["missing"]

    def test_formato_invalido_retorna_400(self, client_com_dados):
        """feature sem __ deve retornar 400."""
        resp = client_com_dados.get(
            "/features/customer_001",
            params={"features": ["open_tickets"]},  # falta group__
        )
        assert resp.status_code == 400

    def test_multiplas_entidades_isoladas(self, client_com_dados):
        resp1 = client_com_dados.get(
            "/features/customer_001",
            params={"features": ["support__open_tickets"]},
        )
        resp2 = client_com_dados.get(
            "/features/customer_002",
            params={"features": ["support__open_tickets"]},
        )
        assert resp1.json()["features"]["support__open_tickets"] == 3
        assert resp2.json()["features"]["support__open_tickets"] == 7


# ── get single feature ────────────────────────────────────────

class TestGetSingleFeature:

    def test_feature_existente_retorna_valor(self, client_com_dados):
        resp = client_com_dados.get(
            "/features/customer_001/support/open_tickets"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["value"] == 3
        assert data["found"] is True

    def test_feature_ausente_no_store(self, client_com_dados):
        """Feature existe no registry mas nao no store para este entity."""
        resp = client_com_dados.get(
            "/features/customer_001/customer/monthly_spend_usd"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["value"] is None
        assert data["found"] is False

    def test_feature_inexistente_no_registry_retorna_404(self, client_com_dados):
        """Feature que nao existe no registry deve retornar 404."""
        resp = client_com_dados.get(
            "/features/customer_001/support/nao_existe"
        )
        assert resp.status_code == 404

    def test_grupo_inexistente_retorna_404(self, client_com_dados):
        resp = client_com_dados.get(
            "/features/customer_001/grupo_fantasma/open_tickets"
        )
        assert resp.status_code == 404


# ── training dataset ──────────────────────────────────────────

class TestTrainingDataset:

    def test_retorna_dataset_com_point_in_time(self, client, offline):
        """
        Escreve historico no offline store.
        API deve retornar o valor correto para cada label_ts.
        """
        offline.write("customer_002", "support", "open_tickets",
                      1, "2024-01-15T00:00:00")
        offline.write("customer_002", "support", "open_tickets",
                      9, "2024-03-01T00:00:00")

        resp = client.post("/training-dataset", json={
            "labels": [
                {"entity_id": "customer_002",
                 "label_ts": "2024-02-01T00:00:00"},
            ],
            "feature_groups": ["support"],
            "feature_names":  ["open_tickets"],
        })

        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert len(rows) == 1
        # point-in-time: deve retornar 1 (janeiro), nao 9 (marco)
        assert rows[0]["support__open_tickets"] == 1
        assert rows[0]["support__open_tickets"] != 9
