import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config.settings import CSV_ENTRADA, ENTRADA_DIR, TEMP_DIR
from modules.utils.loader_processos import carregar_processos


def log(mensagem: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {mensagem}", flush=True)


def validar_pdf(caminho_arquivo):

    arquivo = Path(caminho_arquivo)

    if arquivo.suffix.lower() != ".pdf":
        return False, "extensao nao eh .pdf"

    try:
        assinatura = arquivo.read_bytes()[:5]
    except Exception as exc:
        return False, f"falha ao ler arquivo: {exc}"

    if assinatura != b"%PDF-":
        return False, "assinatura invalida de PDF"

    return True, "ok"


def validar_zip(caminho_arquivo):

    arquivo = Path(caminho_arquivo)

    try:
        if zipfile.is_zipfile(arquivo):
            return True, "ok"
    except Exception as exc:
        return False, f"falha ao validar zip: {exc}"

    try:
        assinatura = arquivo.read_bytes()[:4]
    except Exception as exc:
        return False, f"falha ao ler arquivo: {exc}"

    if assinatura[:2] != b"PK":
        return False, "assinatura invalida de ZIP"

    return True, "ok"


def extrair_numero_sei(texto: str):

    padroes = [
        r"SEI\s*(?:n[oº°]\s*)?(\d{6,9})",
        r"codigo verificador\s*(\d{6,9})",
        r"\b(\d{6,9})\b",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def normalizar_texto_regra(texto: str):

    texto = (texto or "").lower()
    substituicoes = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    return texto


def numero_processo_valido(numero_original: str, numero_limpo: str):

    texto = (numero_original or "").strip()
    if not texto:
        return False

    # Formatos historicos aceitos no IBAMA:
    # 02001.000000/2000-00 (17 digitos limpos)
    # 02001.000000/98-00   (15 digitos limpos)
    padrao = r"^\d{5}\.\d{6}/(?:\d{4}|\d{2})-\d{2}$"
    if not re.fullmatch(padrao, texto):
        return False

    if len(numero_limpo) not in {15, 17}:
        return False

    return True


def documento_indica_eia(documento, nome_analise=""):

    termos = [
        "eia",
        "estudo de impacto ambiental",
        "estudo impacto ambiental",
        "estudo ambiental",
        "estudos ambientais",
        "relatorio ambiental",
        "relatorio de controle ambiental",
        "rca",
        "plano de controle ambiental",
        "pca",
        "relatorio ambiental simplificado",
        "ras",
        "relatorio de impacto ambiental",
        "rima",
        "eia/rima",
        "eir",
    ]

    campos = [
        documento.get("nome", ""),
        documento.get("numero_sei", ""),
        documento.get("link_arvore", ""),
        documento.get("link_direto", ""),
        nome_analise,
    ]

    texto_base = " ".join(normalizar_texto_regra(campo) for campo in campos if campo)

    # Padrao comum do SEI para estudos ambientais anexados ao processo.
    if "estudo" in texto_base and "ibama" in texto_base:
        return True, "estudo_ibama"

    for termo in termos:
        if termo in texto_base:
            return True, termo

    return False, ""


def limpar_temporarios():

    removidos = 0

    for arquivo in Path(TEMP_DIR).glob("*"):
        try:
            if arquivo.is_dir():
                shutil.rmtree(arquivo)
            else:
                arquivo.unlink()
            removidos += 1
        except Exception as exc:
            log(f"Falha ao remover temporario {arquivo.name}: {exc}")

    return removidos


def obter_processos():

    log("Carregando lista de processos...")
    caminho_csv = resolver_csv_entrada()
    log(f"CSV de entrada selecionado: {caminho_csv}")
    processos = carregar_processos(caminho_csv)
    processos_validos = []
    invalidos = 0

    for processo in processos:
        numero_original = processo.get("numero_original", "")
        numero_limpo = processo.get("numero_processo", "")
        if not numero_processo_valido(numero_original, numero_limpo):
            invalidos += 1
            continue
        processos_validos.append(processo)

    if invalidos:
        log(f"{invalidos} linha(s) com numero de processo invalido foram ignoradas.")

    processos = processos_validos
    processos_unicos = []
    vistos = set()
    repetidos = 0

    for processo in processos:
        chave = processo.get("numero_original") or processo.get("numero_processo")
        if chave in vistos:
            repetidos += 1
            continue
        vistos.add(chave)
        processos_unicos.append(processo)

    if repetidos:
        log(f"{repetidos} processo(s) duplicado(s) removido(s) da fila.")
    processos = processos_unicos

    limite = os.getenv("AGIL_MAX_PROCESSOS", "").strip()
    if limite:
        processos = processos[: int(limite)]
        log(f"Limite manual aplicado: {len(processos)} processo(s).")
    else:
        log(f"{len(processos)} processos carregados.")

    return processos


def resolver_csv_entrada():

    # Permite forcar o arquivo de entrada sem alterar codigo.
    csv_env = os.getenv("AGIL_CSV_ENTRADA", "").strip()
    if csv_env:
        caminho_env = Path(csv_env)
        if caminho_env.exists():
            return caminho_env
        raise FileNotFoundError(
            f"Arquivo definido em AGIL_CSV_ENTRADA nao encontrado: {caminho_env}"
        )

    # Prioriza CSVs da pasta data/entrada, escolhendo o mais recente.
    candidatos_entrada = sorted(
        ENTRADA_DIR.glob("*.csv"),
        key=lambda caminho: caminho.stat().st_mtime,
        reverse=True,
    )
    if candidatos_entrada:
        return candidatos_entrada[0]

    # Fallback para compatibilidade com execucoes antigas.
    if Path(CSV_ENTRADA).exists():
        return Path(CSV_ENTRADA)

    raise FileNotFoundError(
        "Nenhum CSV de entrada encontrado. "
        f"Adicione um arquivo .csv em {ENTRADA_DIR} "
        "ou configure AGIL_CSV_ENTRADA."
    )


def extrair_zip_seguro(caminho_zip: Path):

    destino = Path(TEMP_DIR) / f"{caminho_zip.stem}_extraido"
    destino.mkdir(parents=True, exist_ok=True)

    arquivos_extraidos = []

    with zipfile.ZipFile(caminho_zip) as arquivo_zip:
        for membro in arquivo_zip.infolist():
            if membro.is_dir():
                continue

            nome_membro = Path(membro.filename)
            if not nome_membro.name:
                continue

            destino_membro = destino / nome_membro.name
            destino_membro.parent.mkdir(parents=True, exist_ok=True)

            with arquivo_zip.open(membro) as origem, open(destino_membro, "wb") as saida:
                shutil.copyfileobj(origem, saida)

            arquivos_extraidos.append(destino_membro)

    return arquivos_extraidos


def coletar_arquivos_zip(caminho_zip: Path, profundidade=0, profundidade_max=2):

    arquivos_processaveis = []
    extraidos = extrair_zip_seguro(caminho_zip)

    for extraido in extraidos:
        eh_pdf, _ = validar_pdf(extraido)
        if eh_pdf:
            arquivos_processaveis.append(extraido)
            continue

        eh_zip, _ = validar_zip(extraido)
        if eh_zip and profundidade < profundidade_max:
            arquivos_processaveis.extend(
                coletar_arquivos_zip(extraido, profundidade=profundidade + 1)
            )

    return arquivos_processaveis


def preparar_arquivos_para_classificacao(download):

    arquivo = Path(download["arquivo"])
    eh_pdf, _ = validar_pdf(arquivo)
    if eh_pdf:
        return [{"arquivo": arquivo, "nome_origem": download["nome"]}]

    eh_zip, _ = validar_zip(arquivo)
    if not eh_zip:
        return []

    arquivos_zip = coletar_arquivos_zip(arquivo)
    candidatos = []

    for arquivo_extraido in arquivos_zip:
        candidatos.append(
            {
                "arquivo": arquivo_extraido,
                "nome_origem": f"{download['nome']} :: {arquivo_extraido.name}",
            }
        )

    return candidatos
