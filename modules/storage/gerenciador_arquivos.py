import shutil
from pathlib import Path

from config.settings import EIA_DIR


def _sanitizar_parte_nome(valor: str) -> str:

    permitido = []
    for caractere in (valor or "").strip():
        if caractere.isalnum() or caractere in {" ", "-", "_", "."}:
            permitido.append(caractere)
        else:
            permitido.append("_")

    texto = "".join(permitido).strip(" ._")
    return texto or "sem_nome"


def salvar_eia(
    caminho_pdf,
    numero_processo,
    empreendimento,
    numero_sei_documento,
    nome_documento,
):

    nome_pasta = (
        f"{_sanitizar_parte_nome(numero_processo)} - "
        f"{_sanitizar_parte_nome(empreendimento)}"
    )
    pasta_processo = EIA_DIR / nome_pasta

    pasta_processo.mkdir(parents=True, exist_ok=True)

    nome_base = (
        f"{_sanitizar_parte_nome(numero_sei_documento)} - "
        f"{_sanitizar_parte_nome(nome_documento)}"
    )
    destino = pasta_processo / f"{nome_base}.pdf"

    try:

        shutil.move(str(caminho_pdf), destino)

    except Exception as e:

        print("Erro ao mover arquivo:", e)

    return destino
