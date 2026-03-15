import csv
import re
from pathlib import Path


def limpar_numero_processo(numero):
    """
    Remove pontuação do número do processo para facilitar busca no SEI.
    Ex: 02001.004246/2010-56 → 02001004246201056
    """

    if not numero:
        return ""

    return re.sub(r"[^\d]", "", numero)


def carregar_processos(caminho_csv):

    processos = []

    caminho = Path(caminho_csv)

    with open(caminho, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for linha in reader:

            numero_original = linha.get("NUM_PROCESSO_IBAMA")

            if not numero_original:
                continue

            numero_limpo = limpar_numero_processo(numero_original)

            empreendimento = linha.get("NOM_PESSOA", "").strip()

            processo = {
                "numero_processo": numero_limpo,
                "numero_original": numero_original,
                "empreendimento": empreendimento
            }

            processos.append(processo)

    return processos