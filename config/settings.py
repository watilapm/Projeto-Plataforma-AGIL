from pathlib import Path

# =====================================================
# BASE DO PROJETO
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# =====================================================
# PASTAS PRINCIPAIS
# =====================================================

DATA_DIR = BASE_DIR / "data"
ENTRADA_DIR = DATA_DIR / "entrada"
TEMP_DIR = DATA_DIR / "temporarios"
EIA_DIR = DATA_DIR / "EIA"
DATASET_CANDIDATOS_DIR = DATA_DIR / "dataset_candidatos"

LOG_DIR = BASE_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"

# =====================================================
# ARQUIVOS IMPORTANTES
# =====================================================

CSV_ENTRADA = BASE_DIR / "sislic-licencas.csv"
CSV_RESULTADOS = DATA_DIR / "base_classificada.csv"
CSV_DATASET_CANDIDATOS = DATASET_CANDIDATOS_DIR / "catalogo.csv"
CHECKPOINT_EXECUCAO = DATA_DIR / "checkpoint_execucao.json"
EXECUTION_STATE_ARQUIVO = DATA_DIR / "execution_state.json"
EXECUTION_STATE_HISTORICO_DIR = DATA_DIR / "execution_state_history"

MODELO_CLASSIFICADOR = MODELS_DIR / "modelo_eia_vs_outro_ensemble_v4.joblib"

# =====================================================
# CONFIGURAÇÕES DO CLASSIFICADOR
# =====================================================

LIMIAR_CONFIANCA = 0.80

# =====================================================
# CONFIGURAÇÕES DO SCRAPER (SEI)
# =====================================================

SEI_URL = "https://sei.ibama.gov.br"

TIMEOUT_PADRAO = 15
TEMPO_ESPERA_DOWNLOAD = 5

# =====================================================
# CONTROLE DE EXECUÇÃO
# =====================================================

APAGAR_TEMPORARIOS = True
MODO_DEBUG = True
