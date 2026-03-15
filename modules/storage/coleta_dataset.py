import csv
import shutil
from pathlib import Path

from config.settings import CSV_DATASET_CANDIDATOS, DATASET_CANDIDATOS_DIR
from modules.storage.gerenciador_arquivos import _sanitizar_parte_nome


CAMPOS_CATALOGO = [
    "numero_processo",
    "empreendimento",
    "numero_sei_documento",
    "nome_documento",
    "criterio_classificacao",
    "classe_sugerida",
    "motivo_descarte",
    "link_direto_sei",
    "categoria_dataset",
    "caminho_arquivo",
    "caminho_texto",
]


def garantir_catalogo_dataset():

    DATASET_CANDIDATOS_DIR.mkdir(parents=True, exist_ok=True)

    if CSV_DATASET_CANDIDATOS.exists():
        return

    with open(CSV_DATASET_CANDIDATOS, "w", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_CATALOGO)
        writer.writeheader()


def _pasta_processo(numero_processo, empreendimento):

    nome = (
        f"{_sanitizar_parte_nome(numero_processo)} - "
        f"{_sanitizar_parte_nome(empreendimento)}"
    )
    return nome


def salvar_candidato_dataset(
    categoria,
    caminho_arquivo,
    numero_processo,
    empreendimento,
    numero_sei_documento,
    nome_documento,
    texto_extraido="",
):

    pasta = (
        DATASET_CANDIDATOS_DIR
        / categoria
        / _pasta_processo(numero_processo, empreendimento)
    )
    pasta.mkdir(parents=True, exist_ok=True)

    arquivo = Path(caminho_arquivo)
    nome_base = (
        f"{_sanitizar_parte_nome(numero_sei_documento)} - "
        f"{_sanitizar_parte_nome(nome_documento)}"
    )
    destino_arquivo = pasta / f"{nome_base}{arquivo.suffix.lower() or '.bin'}"
    shutil.copy2(arquivo, destino_arquivo)

    destino_texto = ""
    if texto_extraido.strip():
        caminho_texto = pasta / f"{nome_base}.txt"
        caminho_texto.write_text(texto_extraido, encoding="utf-8")
        destino_texto = str(caminho_texto)

    return str(destino_arquivo), destino_texto


def registrar_candidato_dataset(registro: dict):

    garantir_catalogo_dataset()
    linha = {campo: registro.get(campo, "") for campo in CAMPOS_CATALOGO}

    with open(CSV_DATASET_CANDIDATOS, "a", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_CATALOGO)
        writer.writerow(linha)
