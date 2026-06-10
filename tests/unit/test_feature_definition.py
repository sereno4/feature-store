"""
test_feature_definition.py
Valida o contrato Pydantic de cada feature.
Se esses testes passam, a camada de validacao
vai rejeitar dados ruins antes do armazenamento.
"""
import pytest
from pydantic import ValidationError
from src.registry.feature_definition import FeatureDefinition, FeatureGroup


# ── criacao do contrato ───────────────────────────────────────

class TestFeatureDefinitionContrato:

    def test_feature_int_valida(self):
        f = FeatureDefinition(
            name="open_tickets",
            dtype="int",
            description="Tickets abertos",
            min_value=0,
            max_value=1000,
            allow_null=False,
        )
        assert f.name == "open_tickets"
        assert f.dtype == "int"

    def test_feature_string_valida(self):
        f = FeatureDefinition(
            name="plan_type",
            dtype="string",
            description="Plano do cliente",
            allowed_values=["free", "basic", "premium"],
        )
        assert f.allowed_values == ["free", "basic", "premium"]

    def test_feature_float_valida(self):
        f = FeatureDefinition(
            name="monthly_spend_usd",
            dtype="float",
            description="Gasto mensal",
            min_value=0.0,
            max_value=10000.0,
            allow_null=True,
        )
        assert f.allow_null is True

    def test_dtype_invalido_rejeitado(self):
        """dtype fora do Literal -> ValidationError"""
        with pytest.raises(ValidationError):
            FeatureDefinition(
                name="x",
                dtype="decimal",
                description="tipo invalido",
            )

    def test_nome_vazio_rejeitado(self):
        with pytest.raises(ValidationError):
            FeatureDefinition(
                name="",
                dtype="int",
                description="nome vazio",
            )

    def test_range_invertido_rejeitado(self):
        """min_value > max_value deve falhar"""
        with pytest.raises(ValidationError):
            FeatureDefinition(
                name="x",
                dtype="int",
                description="range impossivel",
                min_value=100,
                max_value=10,
            )


# ── validacao de valores ──────────────────────────────────────

class TestValidateValue:

    @pytest.fixture
    def feat_int(self):
        return FeatureDefinition(
            name="open_tickets",
            dtype="int",
            description="Tickets abertos",
            min_value=0,
            max_value=1000,
        )

    @pytest.fixture
    def feat_string(self):
        return FeatureDefinition(
            name="plan_type",
            dtype="string",
            description="Plano",
            allowed_values=["free", "basic", "premium"],
        )

    @pytest.fixture
    def feat_nullable(self):
        return FeatureDefinition(
            name="last_contact",
            dtype="int",
            description="Dias desde contato",
            allow_null=True,
        )

    def test_valor_valido_aceito(self, feat_int):
        ok, err = feat_int.validate_value(5)
        assert ok is True
        assert err is None

    def test_nulo_em_campo_nao_nullable(self, feat_int):
        ok, err = feat_int.validate_value(None)
        assert ok is False
        assert "nao permite nulo" in err

    def test_nulo_em_campo_nullable(self, feat_nullable):
        ok, err = feat_nullable.validate_value(None)
        assert ok is True

    def test_tipo_errado_rejeitado(self, feat_int):
        """string onde esperava int"""
        ok, err = feat_int.validate_value("cinco")
        assert ok is False
        assert "esperava int" in err

    def test_valor_abaixo_do_minimo(self, feat_int):
        ok, err = feat_int.validate_value(-1)
        assert ok is False
        assert "abaixo do minimo" in err

    def test_valor_acima_do_maximo(self, feat_int):
        ok, err = feat_int.validate_value(1001)
        assert ok is False
        assert "acima do maximo" in err

    def test_valor_no_limite_aceito(self, feat_int):
        ok, err = feat_int.validate_value(0)
        assert ok is True
        ok, err = feat_int.validate_value(1000)
        assert ok is True

    def test_string_valida_aceita(self, feat_string):
        ok, err = feat_string.validate_value("premium")
        assert ok is True

    def test_string_invalida_rejeitada(self, feat_string):
        """valor fora dos allowed_values"""
        ok, err = feat_string.validate_value("gold")
        assert ok is False
        assert "nao esta em" in err


# ── feature group ─────────────────────────────────────────────

class TestFeatureGroup:

    @pytest.fixture
    def group(self):
        return FeatureGroup(
            name="support",
            description="Features de suporte",
            entity="customer_id",
            features=[
                FeatureDefinition(
                    name="open_tickets",
                    dtype="int",
                    description="Tickets abertos",
                    min_value=0,
                    max_value=1000,
                ),
                FeatureDefinition(
                    name="resolved_tickets_30d",
                    dtype="int",
                    description="Tickets resolvidos",
                    min_value=0,
                    max_value=500,
                ),
            ],
        )

    def test_get_feature_existente(self, group):
        f = group.get_feature("open_tickets")
        assert f is not None
        assert f.name == "open_tickets"

    def test_get_feature_inexistente(self, group):
        f = group.get_feature("nao_existe")
        assert f is None

    def test_group_tem_entity(self, group):
        assert group.entity == "customer_id"
