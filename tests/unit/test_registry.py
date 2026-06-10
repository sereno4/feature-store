"""
test_registry.py
Valida carregamento do features.yaml, disponibilidade
de grupos e features, e hot reload em runtime.
"""
import time
import pytest
import yaml
from src.registry.registry import FeatureRegistry


@pytest.fixture
def registry():
    return FeatureRegistry(config_path="config/features.yaml")


@pytest.fixture
def registry_tmp(tmp_path):
    """Registry apontando para YAML temporario — para testes de hot reload."""
    config = tmp_path / "features.yaml"
    config.write_text("""
feature_groups:
  customer:
    description: "Features do cliente"
    entity: customer_id
    features:
      - name: account_age_days
        dtype: int
        description: "Idade da conta em dias"
        min_value: 0
        max_value: 36500
        allow_null: false
""")
    return FeatureRegistry(config_path=str(config)), config


# ── carregamento do YAML ──────────────────────────────────────

class TestRegistryCarregamento:

    def test_grupos_carregados(self, registry):
        grupos = registry.list_groups()
        assert "customer" in grupos
        assert "transactions" in grupos
        assert "support" in grupos

    def test_features_do_grupo_customer(self, registry):
        features = registry.list_features("customer")
        assert "account_age_days" in features
        assert "plan_type" in features
        assert "monthly_spend_usd" in features

    def test_features_do_grupo_support(self, registry):
        features = registry.list_features("support")
        assert "open_tickets" in features
        assert "resolved_tickets_30d" in features
        assert "last_contact_days_ago" in features

    def test_get_group_existente(self, registry):
        group = registry.get_group("transactions")
        assert group is not None
        assert group.entity == "customer_id"

    def test_get_group_inexistente(self, registry):
        group = registry.get_group("nao_existe")
        assert group is None

    def test_get_feature_existente(self, registry):
        feat = registry.get_feature("support", "open_tickets")
        assert feat is not None
        assert feat.dtype == "int"
        assert feat.min_value == 0
        assert feat.max_value == 1000

    def test_get_feature_grupo_inexistente(self, registry):
        feat = registry.get_feature("nao_existe", "qualquer")
        assert feat is None

    def test_get_feature_inexistente_no_grupo(self, registry):
        feat = registry.get_feature("customer", "nao_existe")
        assert feat is None

    def test_feature_string_tem_allowed_values(self, registry):
        feat = registry.get_feature("customer", "plan_type")
        assert feat is not None
        assert feat.allowed_values is not None
        assert "premium" in feat.allowed_values

    def test_feature_nullable_carregada(self, registry):
        feat = registry.get_feature("customer", "monthly_spend_usd")
        assert feat is not None
        assert feat.allow_null is True


# ── hot reload ────────────────────────────────────────────────

class TestRegistryHotReload:

    def test_hot_reload_adiciona_nova_feature(self, registry_tmp, tmp_path):
        """
        Modifica o YAML em runtime e verifica que
        o Registry recarrega sem reiniciar.
        """
        reg, config_path = registry_tmp

        # antes da modificacao
        features_antes = reg.list_features("customer")
        assert "account_age_days" in features_antes
        assert "plan_type" not in features_antes

        # modifica o arquivo — adiciona nova feature
        time.sleep(0.05)  # garante mtime diferente
        config_path.write_text("""
feature_groups:
  customer:
    description: "Features do cliente"
    entity: customer_id
    features:
      - name: account_age_days
        dtype: int
        description: "Idade da conta em dias"
        min_value: 0
        max_value: 36500
        allow_null: false
      - name: plan_type
        dtype: string
        description: "Plano do cliente"
        allowed_values: ["free", "basic", "premium"]
        allow_null: false
""")

        # depois da modificacao — Registry deve recarregar
        features_depois = reg.list_features("customer")
        assert "account_age_days" in features_depois
        assert "plan_type" in features_depois

    def test_hot_reload_nao_recarrega_sem_mudanca(self, registry_tmp):
        """
        Se o arquivo nao mudou, o Registry nao recarrega.
        Verifica que o mtime e usado corretamente.
        """
        reg, _ = registry_tmp
        mtime_antes = reg._mtime
        reg._load()
        assert reg._mtime == mtime_antes
