#!/usr/bin/env python

import os

from config.settings import APAGAR_TEMPORARIOS, MODELO_CLASSIFICADOR
from modules.classifier.classificador import ClassificadorEIA
from modules.parser.extrator_texto import extrair_texto_pdf_amostrado
from modules.scraper.scraper_sei import ScraperSEI
from modules.storage.coleta_dataset import (
    registrar_candidato_dataset,
    salvar_candidato_dataset,
)
from modules.utils.pipeline_helpers import (
    documento_indica_eia,
    extrair_numero_sei,
    limpar_temporarios,
    log,
    obter_processos,
    validar_pdf,
    normalizar_texto_regra,
)


TERMOS_PRIORIZADOS = [
    "eia",
    "rima",
    "impacto ambiental",
    "estudo ambiental",
    "volume",
    "anexo",
    "relatorio",
]

TERMOS_IGNORADOS = [
    "recibo",
    "despacho",
    "memorando",
    "oficio",
    "ofício",
    "e-mail",
    "email",
    "protocolo",
]


def persistir_candidato(
    processo,
    download,
    nome_documento,
    numero_sei_documento,
    categoria_dataset,
    classe_sugerida,
    criterio_classificacao,
    motivo_descarte,
    caminho_arquivo,
    texto_extraido="",
):

    numero_processo = processo["numero_original"]
    empreendimento = processo["empreendimento"] or "empreendimento_sem_nome"

    caminho_destino, caminho_texto = salvar_candidato_dataset(
        categoria_dataset,
        caminho_arquivo,
        numero_processo,
        empreendimento,
        numero_sei_documento,
        nome_documento,
        texto_extraido,
    )

    registrar_candidato_dataset(
        {
            "numero_processo": numero_processo,
            "empreendimento": empreendimento,
            "numero_sei_documento": numero_sei_documento,
            "nome_documento": nome_documento,
            "criterio_classificacao": criterio_classificacao,
            "classe_sugerida": classe_sugerida,
            "motivo_descarte": motivo_descarte,
            "link_direto_sei": download.get("link_direto", ""),
            "categoria_dataset": categoria_dataset,
            "caminho_arquivo": caminho_destino,
            "caminho_texto": caminho_texto,
        }
    )


def processar_documento(scraper, classificador, processo, documento):

    nome_documento = documento["nome"]
    nome_normalizado = normalizar_texto_regra(nome_documento)

    try:
        if not any(termo in nome_normalizado for termo in TERMOS_PRIORIZADOS):
            log(f"Documento fora do filtro prioritario: {nome_documento}")
            return

        if any(termo in nome_normalizado for termo in TERMOS_IGNORADOS) and "eia" not in nome_normalizado:
            log(f"Documento ignorado por filtro de baixa prioridade: {nome_documento}")
            return

        log(f"Baixando documento para coleta: {nome_documento}")
        download = scraper.baixar_documento(documento)
        if not download:
            log(f"Sem anexo para coleta: {nome_documento}")
            return

        numero_sei = download.get("numero_sei") or "sem_numero_sei"
        eh_pdf, _ = validar_pdf(download["arquivo"])
        if not eh_pdf:
            log(f"Documento ignorado por nao ser PDF: {nome_documento}")
            return

        arquivo = download["arquivo"]
        nome_analise = download["nome"]
        texto, _paginas = extrair_texto_pdf_amostrado(arquivo)

        numero_sei_final = numero_sei
        if numero_sei_final == "sem_numero_sei":
            numero_sei_final = extrair_numero_sei(texto) or numero_sei

        if not texto.strip():
            persistir_candidato(
                processo,
                download,
                nome_analise,
                numero_sei_final,
                "sem_texto",
                "",
                "",
                "sem_texto_extraido",
                arquivo,
            )
            log(f"Candidato salvo em sem_texto: {nome_analise}")
            return

        heuristica_eia, termo_regra = documento_indica_eia(download, nome_analise)
        if heuristica_eia:
            persistir_candidato(
                processo,
                download,
                nome_analise,
                numero_sei_final,
                "positivos_heuristica",
                "1",
                f"heuristica:{termo_regra}",
                "",
                arquivo,
                texto,
            )
            log(f"Candidato salvo em positivos_heuristica: {nome_analise}")
            return

        resultado = classificador.prever(texto)
        if resultado == 1:
            persistir_candidato(
                processo,
                download,
                nome_analise,
                numero_sei_final,
                "positivos_modelo_v4",
                "1",
                "modelo_v4",
                "",
                arquivo,
                texto,
            )
            log(f"Candidato salvo em positivos_modelo_v4: {nome_analise}")
            return

        persistir_candidato(
            processo,
            download,
            nome_analise,
            numero_sei_final,
            "negativos_modelo_v4",
            "0",
            "modelo_v4",
            "modelo_classificou_nao_eia",
            arquivo,
            texto,
        )
        log(f"Candidato salvo em negativos_modelo_v4: {nome_analise}")

    except Exception as exc:
        log(f"Erro na coleta do documento {nome_documento}: {exc}")


def processar_processo(scraper, classificador, processo, indice, total):

    numero = processo["numero_processo"]
    numero_original = processo["numero_original"]
    empreendimento = processo["empreendimento"] or "empreendimento_sem_nome"

    log("=" * 60)
    log(f"Coleta {indice}/{total}: {numero_original}")
    log(f"Empreendimento: {empreendimento}")

    try:
        scraper.buscar_processo(numero)
        documentos = scraper.listar_documentos()
        log(f"{len(documentos)} documento(s) listados para coleta.")

        for documento in documentos:
            processar_documento(scraper, classificador, processo, documento)

        log(f"Coleta concluida para o processo {numero_original}")

    except Exception as exc:
        log(f"Erro ao coletar processo {numero_original}: {exc}")

    finally:
        if APAGAR_TEMPORARIOS:
            removidos = limpar_temporarios()
            log(
                f"Temporarios limpos apos a coleta do processo {numero_original}: "
                f"{removidos} item(ns) removido(s)."
            )


def main():

    usuario = input("Usuario SEI: ")
    senha = input("Senha SEI: ")

    processos = obter_processos()
    if not processos:
        log("Nenhum processo carregado para coleta.")
        return

    headless = os.getenv("AGIL_HEADLESS", "1").strip() != "0"
    scraper = ScraperSEI(headless=headless)
    classificador = ClassificadorEIA(MODELO_CLASSIFICADOR)

    try:
        log(f"Iniciando login no SEI para coleta (headless={headless})...")
        scraper.login(usuario, senha)

        total = len(processos)
        for indice, processo in enumerate(processos, start=1):
            processar_processo(scraper, classificador, processo, indice, total)

        log("Coleta de dataset finalizada.")

    finally:
        scraper.fechar()


if __name__ == "__main__":
    main()
