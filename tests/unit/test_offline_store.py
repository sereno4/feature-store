"""
test_offline_store.py
Valida o OfflineStore e prova que point-in-time
correctness elimina data leakage.
O teste test_nao_vaza_dado_do_futuro e o mais importante
do projeto — prova o conceito central.
"""
import pytest
import pandas as pd
from src.store.offline_store import OfflineStore


@pytest.fixture
def store(tmp_path):
    """Store isolado por teste — sem efeito colateral."""
    s = OfflineStore(store_path=str(tmp_path / "offline"))
    yield s
    s.clear()


# ── escrita ───────────────────────────────────────────────────

class TestOfflineStoreEscrita:

    def test_write_simples(self, store):
        store.write(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=3,
            feature_ts="2024-01-15T00:00:00",
        )
        assert store.count() == 1

    def test_write_multiplos_eventos(self, store):
        for i, ts in enumerate([
            "2024-01-01T00:00:00",
            "2024-02-01T00:00:00",
            "2024-03-01T00:00:00",
        ]):
            store.write(
                entity_id="customer_001",
                feature_group="support",
                feature_name="open_tickets",
                feature_value=i,
                feature_ts=ts,
            )
        assert store.count() == 3

    def test_write_float(self, store):
        store.write(
            entity_id="customer_001",
            feature_group="customer",
            feature_name="monthly_spend_usd",
            feature_value=49.90,
            feature_ts="2024-01-01T00:00:00",
        )
        val = store.get_point_in_time(
            "customer_001", "customer", "monthly_spend_usd",
            "2024-12-31T00:00:00",
        )
        assert val == 49.90

    def test_write_string(self, store):
        store.write(
            entity_id="customer_001",
            feature_group="customer",
            feature_name="plan_type",
            feature_value="premium",
            feature_ts="2024-01-01T00:00:00",
        )
        val = store.get_point_in_time(
            "customer_001", "customer", "plan_type",
            "2024-12-31T00:00:00",
        )
        assert val == "premium"

    def test_store_vazio_retorna_zero(self, store):
        assert store.count() == 0


# ── point-in-time correctness ─────────────────────────────────

class TestPointInTime:

    def test_retorna_valor_mais_recente_antes_do_ts(self, store):
        """
        Tres snapshots: janeiro, fevereiro, marco.
        Query em fevereiro deve retornar o valor de fevereiro.
        """
        store.write("customer_002", "support", "open_tickets", 1,
                    "2024-01-15T00:00:00")
        store.write("customer_002", "support", "open_tickets", 4,
                    "2024-02-10T00:00:00")
        store.write("customer_002", "support", "open_tickets", 9,
                    "2024-03-01T00:00:00")

        val = store.get_point_in_time(
            "customer_002", "support", "open_tickets",
            as_of="2024-02-15T00:00:00",
        )
        assert val == 4

    def test_nao_vaza_dado_do_futuro(self, store):
        """
        TESTE CENTRAL DO PROJETO.
        Escreve open_tickets=9 em marco.
        Query com timestamp de fevereiro NAO deve retornar 9.
        Retornar 9 aqui seria data leakage.
        """
        store.write("customer_002", "support", "open_tickets", 1,
                    "2024-01-15T00:00:00")
        store.write("customer_002", "support", "open_tickets", 4,
                    "2024-02-10T00:00:00")
        store.write("customer_002", "support", "open_tickets", 9,
                    "2024-03-01T00:00:00")  # futuro em relacao ao label

        val = store.get_point_in_time(
            "customer_002", "support", "open_tickets",
            as_of="2024-02-01T00:00:00",  # label de fevereiro
        )

        # deve retornar 1 (janeiro) — o 4 de fevereiro
        # ainda nao existia em 2024-02-01
        assert val == 1
        assert val != 9, "DATA LEAKAGE: retornou valor do futuro"
        assert val != 4, "retornou valor que ainda nao existia"

    def test_retorna_none_sem_dados_antes_do_ts(self, store):
        """
        Evento existe apenas em marco.
        Query em janeiro deve retornar None —
        a feature nao existia ainda.
        """
        store.write("customer_002", "support", "open_tickets", 9,
                    "2024-03-01T00:00:00")

        val = store.get_point_in_time(
            "customer_002", "support", "open_tickets",
            as_of="2024-01-01T00:00:00",
        )
        assert val is None

    def test_retorna_none_entity_inexistente(self, store):
        store.write("customer_001", "support", "open_tickets", 3,
                    "2024-01-01T00:00:00")
        val = store.get_point_in_time(
            "customer_999", "support", "open_tickets",
            as_of="2024-12-31T00:00:00",
        )
        assert val is None

    def test_retorna_none_store_vazio(self, store):
        val = store.get_point_in_time(
            "customer_001", "support", "open_tickets",
            as_of="2024-01-01T00:00:00",
        )
        assert val is None

    def test_timestamp_exato_incluido(self, store):
        """
        Feature computada exatamente em 2024-02-01.
        Query AS OF 2024-02-01 deve incluir esse valor —
        o operador e <= nao <.
        """
        store.write("customer_001", "support", "open_tickets", 5,
                    "2024-02-01T00:00:00")
        val = store.get_point_in_time(
            "customer_001", "support", "open_tickets",
            as_of="2024-02-01T00:00:00",
        )
        assert val == 5

    def test_entidades_isoladas(self, store):
        """
        Query de customer_001 nao deve retornar
        dados de customer_002 e vice-versa.
        """
        store.write("customer_001", "support", "open_tickets", 2,
                    "2024-01-01T00:00:00")
        store.write("customer_002", "support", "open_tickets", 7,
                    "2024-01-01T00:00:00")

        val_001 = store.get_point_in_time(
            "customer_001", "support", "open_tickets",
            as_of="2024-12-31T00:00:00",
        )
        val_002 = store.get_point_in_time(
            "customer_002", "support", "open_tickets",
            as_of="2024-12-31T00:00:00",
        )
        assert val_001 == 2
        assert val_002 == 7


# ── training dataset ──────────────────────────────────────────

class TestTrainingDataset:

    def test_dataset_sem_data_leakage(self, store):
        """
        customer_002 tem open_tickets crescendo ao longo do tempo.
        Label de fevereiro deve usar o valor de janeiro,
        nao o valor de marco.
        """
        store.write("customer_002", "support", "open_tickets", 1,
                    "2024-01-15T00:00:00")
        store.write("customer_002", "support", "open_tickets", 4,
                    "2024-02-10T00:00:00")
        store.write("customer_002", "support", "open_tickets", 9,
                    "2024-03-01T00:00:00")

        labels = [
            {"entity_id": "customer_002", "label_ts": "2024-02-01T00:00:00"},
        ]
        df = store.get_training_dataset(
            labels=labels,
            feature_groups=["support"],
            feature_names=["open_tickets"],
        )

        assert len(df) == 1
        assert df.iloc[0]["support__open_tickets"] == 1
        assert df.iloc[0]["support__open_tickets"] != 9

    def test_dataset_multiplos_labels(self, store):
        """
        Dois labels diferentes para o mesmo cliente
        devem retornar valores diferentes — cada um
        no seu instante de tempo.
        """
        store.write("customer_001", "support", "open_tickets", 0,
                    "2024-01-01T00:00:00")
        store.write("customer_001", "support", "open_tickets", 2,
                    "2024-02-01T00:00:00")

        labels = [
            {"entity_id": "customer_001", "label_ts": "2024-01-15T00:00:00"},
            {"entity_id": "customer_001", "label_ts": "2024-02-15T00:00:00"},
        ]
        df = store.get_training_dataset(
            labels=labels,
            feature_groups=["support", "support"],
            feature_names=["open_tickets", "open_tickets"],
        )

        assert len(df) == 2
        assert df.iloc[0]["support__open_tickets"] == 0
        assert df.iloc[1]["support__open_tickets"] == 2

    def test_dataset_vazio_sem_dados(self, store):
        labels = [{"entity_id": "nao_existe", "label_ts": "2024-01-01"}]
        df = store.get_training_dataset(
            labels=labels,
            feature_groups=["support"],
            feature_names=["open_tickets"],
        )
        assert len(df) == 1
        assert df.iloc[0]["support__open_tickets"] is None
