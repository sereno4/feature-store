"""
test_online_store.py
Valida o OnlineStore como cache de valores recentes.
Foco em sobrescrita, isolamento entre entidades
e busca de multiplas features em uma chamada.
"""
import pytest
from src.store.online_store import OnlineStore


@pytest.fixture
def store():
    s = OnlineStore()
    yield s
    s.flush()


# ── operacoes basicas ─────────────────────────────────────────

class TestOnlineStoreBasico:

    def test_set_e_get_simples(self, store):
        store.set(
            entity_id="customer_001",
            feature_group="support",
            feature_name="open_tickets",
            feature_value=3,
            feature_ts="2024-02-01T00:00:00",
        )
        val = store.get("customer_001", "support", "open_tickets")
        assert val == 3

    def test_get_inexistente_retorna_none(self, store):
        val = store.get("nao_existe", "support", "open_tickets")
        assert val is None

    def test_set_float(self, store):
        store.set("customer_001", "customer", "monthly_spend_usd",
                  49.90, "2024-01-01T00:00:00")
        val = store.get("customer_001", "customer", "monthly_spend_usd")
        assert val == 49.90

    def test_set_string(self, store):
        store.set("customer_001", "customer", "plan_type",
                  "premium", "2024-01-01T00:00:00")
        val = store.get("customer_001", "customer", "plan_type")
        assert val == "premium"

    def test_store_vazio_count_zero(self, store):
        assert store.count() == 0

    def test_count_apos_writes(self, store):
        store.set("c1", "support", "open_tickets", 1, "2024-01-01")
        store.set("c1", "support", "resolved_tickets_30d", 5, "2024-01-01")
        store.set("c2", "support", "open_tickets", 2, "2024-01-01")
        assert store.count() == 3


# ── sobrescrita ───────────────────────────────────────────────

class TestOnlineStoreSobrescrita:

    def test_set_sobrescreve_valor_anterior(self, store):
        """
        Online store nao acumula historico.
        Segundo set deve substituir o primeiro.
        Este e o comportamento oposto do offline store.
        """
        store.set("customer_001", "support", "open_tickets",
                  1, "2024-01-01T00:00:00")
        store.set("customer_001", "support", "open_tickets",
                  9, "2024-03-01T00:00:00")

        val = store.get("customer_001", "support", "open_tickets")
        assert val == 9
        assert val != 1

    def test_count_nao_cresce_com_sobrescrita(self, store):
        """
        Sobrescrever nao deve aumentar o count —
        e a mesma chave sendo atualizada.
        """
        store.set("c1", "support", "open_tickets", 1, "2024-01")
        store.set("c1", "support", "open_tickets", 2, "2024-02")
        store.set("c1", "support", "open_tickets", 3, "2024-03")
        assert store.count() == 1


# ── isolamento entre entidades ────────────────────────────────

class TestOnlineStoreIsolamento:

    def test_entidades_isoladas(self, store):
        store.set("customer_001", "support", "open_tickets", 2,
                  "2024-01-01T00:00:00")
        store.set("customer_002", "support", "open_tickets", 7,
                  "2024-01-01T00:00:00")

        assert store.get("customer_001", "support", "open_tickets") == 2
        assert store.get("customer_002", "support", "open_tickets") == 7

    def test_delete_remove_apenas_a_feature_alvo(self, store):
        store.set("c1", "support", "open_tickets", 1, "2024-01-01")
        store.set("c1", "support", "resolved_tickets_30d", 5, "2024-01-01")

        store.delete("c1", "support", "open_tickets")

        assert store.get("c1", "support", "open_tickets") is None
        assert store.get("c1", "support", "resolved_tickets_30d") == 5

    def test_flush_remove_tudo(self, store):
        store.set("c1", "support", "open_tickets", 1, "2024-01-01")
        store.set("c2", "support", "open_tickets", 2, "2024-01-01")
        store.flush()
        assert store.count() == 0


# ── get_many ──────────────────────────────────────────────────

class TestOnlineStoreGetMany:

    def test_get_many_retorna_todas_features(self, store):
        """
        get_many e o metodo usado pela serving API.
        Busca multiplas features em uma chamada.
        """
        store.set("customer_001", "support", "open_tickets",
                  2, "2024-01-01T00:00:00")
        store.set("customer_001", "customer", "plan_type",
                  "premium", "2024-01-01T00:00:00")
        store.set("customer_001", "transactions", "tx_count_30d",
                  45, "2024-01-01T00:00:00")

        result = store.get_many(
            entity_id="customer_001",
            features=[
                ("support", "open_tickets"),
                ("customer", "plan_type"),
                ("transactions", "tx_count_30d"),
            ],
        )

        assert result["support__open_tickets"] == 2
        assert result["customer__plan_type"] == "premium"
        assert result["transactions__tx_count_30d"] == 45

    def test_get_many_retorna_none_para_ausentes(self, store):
        """
        Feature nao existente no store deve retornar None
        sem quebrar as outras.
        """
        store.set("customer_001", "support", "open_tickets",
                  2, "2024-01-01T00:00:00")

        result = store.get_many(
            entity_id="customer_001",
            features=[
                ("support", "open_tickets"),
                ("customer", "plan_type"),    # nao existe
            ],
        )

        assert result["support__open_tickets"] == 2
        assert result["customer__plan_type"] is None
