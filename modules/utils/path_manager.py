from config.settings import (
    DATA_DIR,
    ENTRADA_DIR,
    TEMP_DIR,
    EIA_DIR,
    DATASET_CANDIDATOS_DIR,
    LOG_DIR,
    MODELS_DIR,
    CSV_RESULTADOS,
)

import os


def criar_pastas():
    """
    Garante que todas as pastas necessárias existam.
    """
    pastas = [
        DATA_DIR,
        ENTRADA_DIR,
        TEMP_DIR,
        EIA_DIR,
        DATASET_CANDIDATOS_DIR,
        LOG_DIR,
        MODELS_DIR,
    ]

    for pasta in pastas:
        os.makedirs(pasta, exist_ok=True)


def inicializar_csv_resultados():
    """
    Cria o CSV de resultados caso ainda não exista.
    """
    if not CSV_RESULTADOS.exists():
        with open(CSV_RESULTADOS, "w", encoding="utf-8") as f:
            f.write(
                "processo,empreendimento,documento,classe,probabilidade,link,caminho_pdf\n"
            )


def inicializar_ambiente():
    """
    Inicializa todo o ambiente do AGIL.
    """
    criar_pastas()
    inicializar_csv_resultados()
