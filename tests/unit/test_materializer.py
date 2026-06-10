"""
test_materializer.py
Valida que o Materializer sincroniza offline -> online
sempre com o valor mais recente de cada feature.
"""
import pytest
from src.store.offline_store import OfflineStore
from src.store.online_store import OnlineStore
from src.materializer.materializer import Materializer


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
def materializer(offline, online):
    return Materializer(offline_store=offline, online_store=online)


# ── materialize_all ───────────────────────────────────────────

class TestMaterializeAll:

    def test_store_vazio_sucesso_sem_erros(self, materializer):
        """Store vazio nao e um erro — apenas nada para fazer."""
        result = materializer.materialize_all()
        assert result.success is True
        assert result.features_materialized == 0
        assert result.errors == [] or "vazio" in result.errors[0]

    def test_materializa_feature_simples(self, materializer, offline, online):
        offline.write("customer_001", "support", "open_tickets",
                      3, "2024-01-15T00:00:00")

        result = materializer.materialize_all()

        assert result.success is True
        assert result.features_materialized == 1
        assert online.get("customer_001", "support", "open_tickets") == 3

    def test_materializa_apenas_valor_mais_recente(
        self, materializer, offline, online
    ):
        """
        Offline tem 3 snapshots do mesmo cliente.
        Online deve ficar so com o valor mais recente.
        Nao deve materializar historico — so o estado atual.
        """
        offline.write("customer_002", "support", "open_tickets",
                      1, "2024-01-15T00:00:00")
        offline.write("customer_002", "support", "open_tickets",
                      4, "2024-02-10T00:00:00")
        offline.write("customer_002", "support", "open_tickets",
                      9, "2024-03-01T00:00:00")

        result = materializer.materialize_all()

        assert result.success is True
        assert result.features_materialized == 1  # uma feature unica
        val = online.get("customer_002", "support", "open_tickets")
        assert val == 9    # o mais recente
        assert val != 1    # nao o primeiro
        assert val != 4    # nao o do meio

    def test_materializa_multiplas_entidades(
        self, materializer, offline, online
    ):
        offline.write("customer_001", "support", "open_tickets",
                      2, "2024-01-01T00:00:00")
        offline.write("customer_002", "support", "open_tickets",
                      7, "2024-01-01T00:00:00")
        offline.write("customer_003", "support", "open_tickets",
                      0, "2024-01-01T00:00:00")

        result = materializer.materialize_all()

        assert result.features_materialized == 3
        assert "customer_001" in result.entities_updated
        assert "customer_002" in result.entities_updated
        assert "customer_003" in result.entities_updated

    def test_materializa_multiplas_features(
        self, materializer, offline, online
    ):
        offline.write("customer_001", "support", "open_tickets",
                      2, "2024-01-01T00:00:00")
        offline.write("customer_001", "customer", "plan_type",
                      "premium", "2024-01-01T00:00:00")
        offline.write("customer_001", "transactions", "tx_count_30d",
                      45, "2024-01-01T00:00:00")

        result = materializer.materialize_all()

        assert result.features_materialized == 3
        assert online.get("customer_001", "support", "open_tickets") == 2
        assert online.get("customer_001", "customer", "plan_type") == "premium"
        assert online.get("customer_001", "transactions", "tx_count_30d") == 45

    def test_result_tem_timestamps(self, materializer):
        result = materializer.materialize_all()
        assert result.started_at != ""
        assert result.finished_at != ""


# ── materialize_entity ────────────────────────────────────────

class TestMaterializeEntity:

    def test_materializa_so_a_entidade_alvo(
        self, materializer, offline, online
    ):
        """
        Dois clientes no offline store.
        Materializar customer_001 nao deve tocar customer_002.
        """
        offline.write("customer_001", "support", "open_tickets",
                      3, "2024-01-01T00:00:00")
        offline.write("customer_002", "support", "open_tickets",
                      7, "2024-01-01T00:00:00")

        result = materializer.materialize_entity("customer_001")

        assert result.success is True
        assert result.features_materialized == 1
        assert online.get("customer_001", "support", "open_tickets") == 3
        assert online.get("customer_002", "support", "open_tickets") is None

    def test_entidade_inexistente_sucesso_sem_features(
        self, materializer, offline
    ):
        offline.write("customer_001", "support", "open_tickets",
                      3, "2024-01-01T00:00:00")

        result = materializer.materialize_entity("nao_existe")

        assert result.success is True
        assert result.features_materialized == 0
