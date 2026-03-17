import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from config.settings import CSV_ACOMPANHAMENTO_EXECUCOES, EXECUTION_STATE_HISTORICO_DIR


CAMPOS_ACOMPANHAMENTO = [
    "registrado_em",
    "origem",
    "run_id",
    "status_execucao",
    "inicio_execucao",
    "fim_execucao",
    "processos_planejados",
    "numero_processo",
    "empreendimento",
    "status_processo",
    "erro_processo",
    "documentos_listados",
    "documentos_processados",
    "eias_encontrados",
    "duracao_segundos",
    "tempo_estimado_humano_min",
    "tempo_estimado_humano_hhmm",
]


def _normalizar_datetime(valor):
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    return str(valor or "").strip()


def _normalizar_erro(valor: str, limite: int = 280):
    texto = " ".join(str(valor or "").split())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3] + "..."


def _formatar_hhmm(total_minutos: float):
    minutos_int = max(0, int(round(total_minutos)))
    horas, minutos = divmod(minutos_int, 60)
    return f"{horas:02d}:{minutos:02d}"


def _estimar_tempo_humano_min(documentos_listados: int, documentos_processados: int, eias_encontrados: int):
    """
    Heuristica de esforco manual por processo:
    - base: 4 min por processo (abrir processo, contexto e fechamento)
    - triagem: 0.25 min por documento apenas listado (nao processado)
    - processamento: 1.75 min por documento processado (abrir, baixar e ler/classificar)
    - EIA confirmado: +2.5 min por EIA (validacao e registro final)
    """
    listados = max(0, int(documentos_listados or 0))
    processados = max(0, int(documentos_processados or 0))
    eias = max(0, int(eias_encontrados or 0))

    apenas_triagem = max(0, listados - processados)

    estimado = (
        4.0
        + (0.25 * apenas_triagem)
        + (1.75 * processados)
        + (2.5 * eias)
    )

    return round(estimado, 1)


def garantir_csv_acompanhamento():
    CSV_ACOMPANHAMENTO_EXECUCOES.parent.mkdir(parents=True, exist_ok=True)

    if CSV_ACOMPANHAMENTO_EXECUCOES.exists():
        with open(CSV_ACOMPANHAMENTO_EXECUCOES, newline="", encoding="utf-8") as arquivo:
            leitor = csv.reader(arquivo)
            cabecalho = next(leitor, [])

        if cabecalho == CAMPOS_ACOMPANHAMENTO:
            return

        with open(CSV_ACOMPANHAMENTO_EXECUCOES, newline="", encoding="utf-8") as arquivo:
            leitor = csv.DictReader(arquivo)
            linhas = list(leitor)

        with open(CSV_ACOMPANHAMENTO_EXECUCOES, "w", newline="", encoding="utf-8") as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_ACOMPANHAMENTO)
            writer.writeheader()
            for linha in linhas:
                writer.writerow({campo: linha.get(campo, "") for campo in CAMPOS_ACOMPANHAMENTO})
        return

    with open(CSV_ACOMPANHAMENTO_EXECUCOES, "w", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_ACOMPANHAMENTO)
        writer.writeheader()


def _chaves_existentes(caminho_csv: Path):
    chaves = set()
    if not caminho_csv.exists():
        return chaves

    with open(caminho_csv, newline="", encoding="utf-8") as arquivo:
        leitor = csv.DictReader(arquivo)
        for linha in leitor:
            run_id = (linha.get("run_id") or "").strip()
            numero = (linha.get("numero_processo") or "").strip()
            if run_id and numero:
                chaves.add((run_id, numero))
    return chaves


def _linhas_acompanhamento(
    run_id: str,
    status_execucao: str,
    inicio_execucao,
    fim_execucao,
    processos_planejados: int,
    processos_resumidos: Iterable[dict],
    origem: str,
):
    registrado_em = datetime.now().isoformat(timespec="seconds")
    inicio_iso = _normalizar_datetime(inicio_execucao)
    fim_iso = _normalizar_datetime(fim_execucao)

    linhas = []
    for processo in processos_resumidos or []:
        docs_listados = int(processo.get("documentos_listados") or 0)
        docs_processados = int(processo.get("documentos_processados") or 0)
        eias = int(processo.get("eias_encontrados") or 0)
        tempo_estimado = _estimar_tempo_humano_min(
            documentos_listados=docs_listados,
            documentos_processados=docs_processados,
            eias_encontrados=eias,
        )

        linhas.append(
            {
                "registrado_em": registrado_em,
                "origem": (origem or "").strip(),
                "run_id": (run_id or "").strip(),
                "status_execucao": (status_execucao or "").strip(),
                "inicio_execucao": inicio_iso,
                "fim_execucao": fim_iso,
                "processos_planejados": int(processos_planejados or 0),
                "numero_processo": (processo.get("numero_processo") or "").strip(),
                "empreendimento": (processo.get("empreendimento") or "").strip(),
                "status_processo": (processo.get("status") or "").strip(),
                "erro_processo": _normalizar_erro(processo.get("erro_processo", "")),
                "documentos_listados": docs_listados,
                "documentos_processados": docs_processados,
                "eias_encontrados": eias,
                "duracao_segundos": int(processo.get("duracao_segundos") or 0),
                "tempo_estimado_humano_min": f"{tempo_estimado:.1f}",
                "tempo_estimado_humano_hhmm": _formatar_hhmm(tempo_estimado),
            }
        )

    return linhas


def registrar_acompanhamento_execucoes(
    run_id: str,
    status_execucao: str,
    inicio_execucao,
    fim_execucao,
    processos_planejados: int,
    processos_resumidos: Iterable[dict],
    origem: str,
):
    garantir_csv_acompanhamento()

    linhas = _linhas_acompanhamento(
        run_id=run_id,
        status_execucao=status_execucao,
        inicio_execucao=inicio_execucao,
        fim_execucao=fim_execucao,
        processos_planejados=processos_planejados,
        processos_resumidos=processos_resumidos,
        origem=origem,
    )

    if not linhas:
        return 0

    chaves = _chaves_existentes(CSV_ACOMPANHAMENTO_EXECUCOES)
    novas = []
    for linha in linhas:
        chave = (linha["run_id"], linha["numero_processo"])
        if not linha["run_id"] or not linha["numero_processo"]:
            continue
        if chave in chaves:
            continue
        chaves.add(chave)
        novas.append(linha)

    if not novas:
        return 0

    with open(CSV_ACOMPANHAMENTO_EXECUCOES, "a", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_ACOMPANHAMENTO)
        writer.writerows(novas)

    return len(novas)


def sincronizar_acompanhamento_com_historico(historico_dir: Path = EXECUTION_STATE_HISTORICO_DIR):
    historico = Path(historico_dir)
    if not historico.exists():
        return 0

    total_registros = 0
    for arquivo_json in sorted(historico.glob("*.json")):
        try:
            with open(arquivo_json, encoding="utf-8") as arquivo:
                estado = json.load(arquivo)
        except Exception:
            continue

        if not isinstance(estado, dict):
            continue

        total_registros += registrar_acompanhamento_execucoes(
            run_id=estado.get("run_id", ""),
            status_execucao=estado.get("status", ""),
            inicio_execucao=estado.get("inicio_execucao", ""),
            fim_execucao=estado.get("fim_execucao", "") or estado.get("heartbeat_em", ""),
            processos_planejados=int(estado.get("processos_planejados") or 0),
            processos_resumidos=estado.get("resumo_processos") or [],
            origem="historico_sync",
        )

    return total_registros
