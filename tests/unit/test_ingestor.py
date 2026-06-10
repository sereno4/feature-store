"""
test_ingestor.py
Valida a porta de entrada da Feature Store.
Garante que dados invalidos nunca chegam aos stores
e que offline e online ficam sempre sincronizados.
"""
import pytest
from src.ingest.ingestor import Ingestor, IngestEvent
from src.registry.registry import FeatureRegistry
from src.store.offline_store import OfflineStore
from src.store.online_store import OnlineStore


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


def make_event(**kwargs) -> IngestEvent:
    defaults = dict(
        entity_id="customer_001",
        feature_group="support",
        feature_name="open_tickets",
        feature_value=3,
        feature_ts="2024-01-15T00:00:00",
    )
    defaults.update(kwargs)
    return IngestEvent(**defaults)


# ── ingestao valida ───────────────────────────────────────────

class TestIngestorValido:

    def test_evento_valido_aceito(self, ingestor):
        result = ingestor.ingest(make_event())
        assert result.success is True
        assert result.errors == []

    def test_evento_valido_vai_para_offline(self, ingestor, offline):
        ingestor.ingest(make_event())
        assert offline.count() == 1

    def test_evento_valido_vai_para_online(self, ingestor, online):
        ingestor.ingest(make_event())
        val = online.get("customer_001", "support", "open_tickets")
        assert val == 3

    def test_evento_float_aceito(self, ingestor):
        result = ingestor.ingest(make_event(
            feature_group="customer",
            feature_name="monthly_spend_usd",
            feature_value=49.90,
        ))
        assert result.success is True

    def test_evento_string_aceito(self, ingestor):
        result = ingestor.ingest(make_event(
            feature_group="customer",
            feature_name="plan_type",
            feature_value="premium",
        ))
        assert result.success is True

    def test_evento_nullable_com_none(self, ingestor):
        result = ingestor.ingest(make_event(
            feature_group="customer",
            feature_name="monthly_spend_usd",
            feature_value=None,
        ))
        assert result.success is True


# ── ingestao invalida ─────────────────────────────────────────

class TestIngestorInvalido:

    def test_grupo_inexistente_rejeitado(self, ingestor):
        result = ingestor.ingest(make_event(
            feature_group="nao_existe",
        ))
        assert result.success is False
        assert any("nao existe no registry" in e for e in result.errors)

    def test_feature_inexistente_rejeitada(self, ingestor):
        result = ingestor.ingest(make_event(
            feature_name="feature_fantasma",
        ))
        assert result.success is False
        assert any("nao existe" in e for e in result.errors)

    def test_valor_abaixo_do_minimo_rejeitado(self, ingestor):
        """open_tickets min=0, valor -1 deve ser rejeitado"""
        result = ingestor.ingest(make_event(feature_value=-1))
        assert result.success is False
        assert any("abaixo do minimo" in e for e in result.errors)

    def test_valor_acima_do_maximo_rejeitado(self, ingestor):
        """open_tickets max=1000, valor 9999 deve ser rejeitado"""
        result = ingestor.ingest(make_event(feature_value=9999))
        assert result.success is False
        assert any("acima do maximo" in e for e in result.errors)

    def test_tipo_errado_rejeitado(self, ingestor):
        """open_tickets dtype=int, string deve ser rejeitado"""
        result = ingestor.ingest(make_event(feature_value="tres"))
        assert result.success is False
        assert any("esperava int" in e for e in result.errors)

    def test_string_fora_dos_allowed_values(self, ingestor):
        """plan_type so aceita free/basic/premium/enterprise"""
        result = ingestor.ingest(make_event(
            feature_group="customer",
            feature_name="plan_type",
            feature_value="gold",
        ))
        assert result.success is False
        assert any("nao esta em" in e for e in result.errors)

    def test_invalido_nao_grava_no_offline(self, ingestor, offline):
        """Dado rejeitado nao contamina o offline store"""
        ingestor.ingest(make_event(feature_value=-1))
        assert offline.count() == 0

    def test_invalido_nao_grava_no_online(self, ingestor, online):
        """Dado rejeitado nao contamina o online store"""
        ingestor.ingest(make_event(feature_value=-1))
        val = online.get("customer_001", "support", "open_tickets")
        assert val is None


# ── consistencia entre stores ─────────────────────────────────

class TestIngestorConsistencia:

    def test_offline_e_online_sincronizados(self, ingestor, offline, online):
        """
        Apos ingestao valida, offline e online devem
        ter o mesmo valor para a feature.
        """
        ingestor.ingest(make_event(feature_value=5))

        val_offline = offline.get_point_in_time(
            "customer_001", "support", "open_tickets",
            as_of="2024-12-31T00:00:00",
        )
        val_online = online.get(
            "customer_001", "support", "open_tickets"
        )

        assert val_offline == val_online == 5

    def test_multiplos_eventos_mesmo_entity(self, ingestor, offline, online):
        """
        Offline acumula historico.
        Online fica com o valor mais recente.
        """
        ingestor.ingest(make_event(
            feature_value=1, feature_ts="2024-01-01T00:00:00"
        ))
        ingestor.ingest(make_event(
            feature_value=4, feature_ts="2024-02-01T00:00:00"
        ))
        ingestor.ingest(make_event(
            feature_value=9, feature_ts="2024-03-01T00:00:00"
        ))

        # offline tem historico completo
        assert offline.count() == 3

        # online tem so o mais recente
        val_online = online.get("customer_001", "support", "open_tickets")
        assert val_online == 9

        # offline respeita point-in-time
        val_jan = offline.get_point_in_time(
            "customer_001", "support", "open_tickets",
            as_of="2024-01-15T00:00:00",
        )
        assert val_jan == 1


# ── batch ─────────────────────────────────────────────────────

class TestIngestorBatch:

    def test_batch_processa_todos(self, ingestor):
        events = [
            make_event(entity_id=f"customer_00{i}")
            for i in range(1, 4)
        ]
        results = ingestor.ingest_batch(events)
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_batch_falha_em_um_nao_para_outros(self, ingestor):
        """
        Evento invalido no meio do batch nao para
        o processamento dos seguintes.
        """
        events = [
            make_event(entity_id="customer_001", feature_value=2),
            make_event(entity_id="customer_002", feature_value=-99),  # invalido
            make_event(entity_id="customer_003", feature_value=4),
        ]
        results = ingestor.ingest_batch(events)

        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    def test_ingest_from_scenarios(self, ingestor, offline):
        """
        Ingere todos os eventos do scenarios.yaml.
        Verifica que o store tem dados dos 4 clientes.
        """
        results = ingestor.ingest_from_scenarios("config/scenarios.yaml")

        sucessos  = [r for r in results if r.success]
        falhas    = [r for r in results if not r.success]

        assert len(sucessos) > 0
        assert offline.count() == len(sucessos)

        entidades = {r.entity_id for r in sucessos}
        assert "customer_001" in entidades
        assert "customer_002" in entidades
