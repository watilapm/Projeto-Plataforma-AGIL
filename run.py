#!/usr/bin/env python

import os
import zipfile
from datetime import datetime
from time import monotonic

from modules.classifier.classificador import ClassificadorEIA
from modules.notifications.email_report import enviar_relatorio_execucao
from modules.parser.extrator_texto import extrair_texto_e_paginas_pdf
from modules.scraper.scraper_sei import ScraperSEI
from modules.storage.checkpoint_execucao import CheckpointExecucao
from modules.storage.gerenciador_arquivos import salvar_eia
from modules.storage.registro_resultados import registrar_resultado
from modules.utils.env_loader import carregar_env_arquivo
from modules.utils.pipeline_helpers import (
    extrair_numero_sei,
    limpar_temporarios,
    log,
    normalizar_texto_regra,
    obter_processos,
    preparar_arquivos_para_classificacao,
)
from config.settings import APAGAR_TEMPORARIOS, MODELO_CLASSIFICADOR


def documento_estrutural(nome_documento: str):

    nome = (nome_documento or "").strip()
    nome_normalizado = normalizar_texto_regra(nome)

    if nome_normalizado in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}:
        return True

    if nome_normalizado in {"anexo", "volume"}:
        return True

    return False


def documento_raiz_processo(nome_documento: str, numero_original: str, numero_limpo: str):

    nome = normalizar_texto_regra(nome_documento or "")
    numero_fmt = normalizar_texto_regra(numero_original or "")
    numero_raw = normalizar_texto_regra(numero_limpo or "")

    return nome in {numero_fmt, numero_raw}


def documento_indica_eia_titulo(documento, nome_analise=""):

    campos = [
        documento.get("nome", ""),
        documento.get("numero_sei", ""),
        documento.get("link_arvore", ""),
        nome_analise,
    ]
    texto_base = " ".join(normalizar_texto_regra(campo) for campo in campos if campo)

    if "estudo" in texto_base and "ibama" in texto_base:
        return True, "estudo_ibama"

    termos = [
        "eia",
        "estudo de impacto ambiental",
    ]
    for termo in termos:
        if termo in texto_base:
            return True, termo

    return False, ""


def documento_descartavel_pre_download(nome_documento: str):

    nome = normalizar_texto_regra(nome_documento or "")
    if not nome:
        return False, ""

    # Nunca descartar no pre-filtro se houver indicio direto de EIA/estudo ambiental.
    if "eia" in nome or "estudo de impacto ambiental" in nome:
        return False, ""
    if "estudo" in nome and "ibama" in nome:
        return False, ""

    termos_descarte = [
        "e-mail",
        "email",
        "parecer",
        "despacho",
        "oficio",
        "minuta",
        "solicitacao",
        "solicitação",
        "recibo eletronico",
        "recibo eletrônico",
        "comprovante",
        "certidao",
        "certidão",
        "cnh",
        "cpf",
        "cnpj",
    ]
    for termo in termos_descarte:
        if termo in nome:
            return True, termo

    return False, ""


def processar_documento(scraper, classificador, processo, documento, documento_idx=0, total_documentos=0):

    nome_documento = documento["nome"]
    numero = processo["numero_processo"]
    numero_original = processo["numero_original"]
    empreendimento = processo["empreendimento"] or "empreendimento_sem_nome"

    try:
        if documento_estrutural(nome_documento):
            log(f"Documento estrutural ignorado: {nome_documento}")
            return False

        if documento_raiz_processo(nome_documento, numero_original, numero):
            log(f"Item raiz do processo ignorado: {nome_documento}")
            return False

        descartavel, motivo_descarte = documento_descartavel_pre_download(nome_documento)
        if descartavel:
            log(
                f"Documento ignorado por heuristica pre-download "
                f"(termo='{motivo_descarte}'): {nome_documento}"
            )
            return False

        prefixo_progresso = ""
        if total_documentos:
            prefixo_progresso = f"[doc {documento_idx + 1}/{total_documentos}] "

        log(f"{prefixo_progresso}Baixando documento: {nome_documento}")
        download = scraper.baixar_documento(documento)
        if not download:
            log(f"{prefixo_progresso}Documento sem anexo baixavel: {nome_documento}")
            return False

        candidatos = preparar_arquivos_para_classificacao(download)
        if not candidatos:
            log(f"{prefixo_progresso}Ignorando documento {nome_documento}: formato nao suportado")
            return False

        numero_sei = download.get("numero_sei") or "sem_numero_sei"
        eia_identificado = False

        for candidato in candidatos:
            arquivo = candidato["arquivo"]
            nome_analise = candidato["nome_origem"]
            criterio_classificacao = ""

            heuristica_eia, termo_regra = documento_indica_eia_titulo(download, nome_analise)
            if heuristica_eia:
                numero_sei_final = numero_sei
                criterio_classificacao = f"heuristica_titulo:{termo_regra}"
                log(
                    f"Documento marcado como EIA por heuristica de titulo "
                    f"(termo='{termo_regra}'): {nome_analise}"
                )
                destino = salvar_eia(
                    arquivo,
                    numero_original,
                    empreendimento,
                    numero_sei_final,
                    nome_analise,
                )
                registrar_resultado(
                    {
                        "numero_processo": numero_original,
                        "empreendimento": empreendimento,
                        "numero_sei_documento": numero_sei_final,
                        "nome_documento": nome_analise,
                        "criterio_classificacao": criterio_classificacao,
                        "link_direto_sei": download.get("link_direto", ""),
                        "caminho_pdf": str(destino),
                    }
                )
                log(
                    "EIA identificado e salvo: "
                    f"processo={numero_original} documento={numero_sei_final} arquivo={destino.name}"
                )
                eia_identificado = True
                continue

            log(f"{prefixo_progresso}Analisando arquivo: {arquivo.name}")
            texto, _paginas = extrair_texto_e_paginas_pdf(arquivo)
            if not texto.strip():
                log(f"{prefixo_progresso}Arquivo sem texto extraido: {nome_analise}")
                continue

            numero_sei_final = numero_sei
            if numero_sei_final == "sem_numero_sei":
                numero_sei_final = extrair_numero_sei(texto) or numero_sei

            criterio_classificacao = "modelo_v4"
            resultado = classificador.prever(texto)

            if resultado != 1:
                log(f"{prefixo_progresso}Arquivo nao classificado como EIA: {nome_analise}")
                continue

            destino = salvar_eia(
                arquivo,
                numero_original,
                empreendimento,
                numero_sei_final,
                nome_analise,
            )
            registrar_resultado(
                {
                    "numero_processo": numero_original,
                    "empreendimento": empreendimento,
                    "numero_sei_documento": numero_sei_final,
                    "nome_documento": nome_analise,
                    "criterio_classificacao": criterio_classificacao,
                    "link_direto_sei": download.get("link_direto", ""),
                    "caminho_pdf": str(destino),
                }
            )
            log(
                "EIA identificado e salvo: "
                f"processo={numero_original} documento={numero_sei_final} arquivo={destino.name}"
            )
            eia_identificado = True

        if not eia_identificado:
            log(f"{prefixo_progresso}Documento nao classificado como EIA: {nome_documento}")

        return eia_identificado

    except (zipfile.BadZipFile, OSError) as exc:
        log(
            f"Falha ao abrir ZIP do documento "
            f"[doc {documento_idx + 1}/{total_documentos}] {nome_documento}: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return False

    except Exception as exc:
        log(
            f"Erro ao processar documento "
            f"[doc {documento_idx + 1}/{total_documentos}] {nome_documento}: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return False


def processar_processo(scraper, classificador, processo, indice, total, checkpoint=None):

    numero = processo["numero_processo"]
    numero_original = processo["numero_original"]
    empreendimento = processo["empreendimento"] or "empreendimento_sem_nome"

    log("=" * 60)
    log(f"Processo {indice}/{total}: {numero_original}")
    log(f"Empreendimento: {empreendimento}")

    eias_encontrados = 0
    documentos_listados = 0
    documentos_processados = 0
    erros_documento = 0
    status = "concluido"
    erro_processo = ""
    inicio = monotonic()

    try:
        scraper.buscar_processo(numero)
        documentos = scraper.listar_documentos()
        documentos_listados = len(documentos)
        log(f"{len(documentos)} documento(s) listados para o processo.")

        inicio_documento = 0
        if checkpoint:
            inicio_documento = checkpoint.obter_indice_retorno(numero_original)
            if inicio_documento > 0:
                log(
                    f"Retomando processo {numero_original} no documento "
                    f"{inicio_documento + 1}/{len(documentos)}."
                )

            checkpoint.iniciar_processo(
                numero_original=numero_original,
                empreendimento=empreendimento,
                indice_processo=indice,
                total_processos=total,
                total_documentos=len(documentos),
                proximo_documento_idx=inicio_documento,
            )

        for documento_idx, documento in enumerate(documentos):
            if documento_idx < inicio_documento:
                continue

            documentos_processados += 1
            if processar_documento(
                scraper=scraper,
                classificador=classificador,
                processo=processo,
                documento=documento,
                documento_idx=documento_idx,
                total_documentos=len(documentos),
            ):
                eias_encontrados += 1

            if checkpoint:
                checkpoint.marcar_documento_processado(
                    numero_original=numero_original,
                    proximo_idx=documento_idx + 1,
                    nome_documento=documento.get("nome", ""),
                    eias=eias_encontrados,
                )

        log(
            f"Processo concluido: {numero_original} | "
            f"EIA(s) identificados: {eias_encontrados}"
        )
        if checkpoint:
            checkpoint.marcar_processo_concluido(numero_original)

    except Exception as exc:
        status = "erro"
        erro_processo = f"{exc.__class__.__name__}: {exc}"
        erros_documento += 1
        log(f"Erro ao processar processo {numero_original}: {exc}")

    finally:
        if APAGAR_TEMPORARIOS:
            removidos = limpar_temporarios()
            log(
                f"Temporarios limpos apos o processo {numero_original}: "
                f"{removidos} arquivo(s) removido(s)."
            )

    duracao_segundos = int(monotonic() - inicio)
    return {
        "numero_processo": numero_original,
        "empreendimento": empreendimento,
        "status": status,
        "erro_processo": erro_processo,
        "documentos_listados": documentos_listados,
        "documentos_processados": documentos_processados,
        "erros_documento": erros_documento,
        "eias_encontrados": eias_encontrados,
        "duracao_segundos": duracao_segundos,
    }


def _formatar_duracao(segundos: int):
    horas, resto = divmod(max(0, int(segundos)), 3600)
    minutos, secs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{secs:02d}"


def montar_relatorio_execucao(
    inicio_execucao: datetime,
    fim_execucao: datetime,
    processos_planejados: int,
    processos_resumidos: list,
):
    total_execucao = int((fim_execucao - inicio_execucao).total_seconds())
    processos_concluidos = sum(1 for p in processos_resumidos if p["status"] == "concluido")
    processos_erro = processos_planejados - processos_concluidos
    docs_listados = sum(p["documentos_listados"] for p in processos_resumidos)
    docs_processados = sum(p["documentos_processados"] for p in processos_resumidos)
    erros_documento = sum(p["erros_documento"] for p in processos_resumidos)
    eias_total = sum(p["eias_encontrados"] for p in processos_resumidos)

    linhas = [
        "Relatorio de Execucao AGIL",
        f"Inicio: {inicio_execucao.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Fim: {fim_execucao.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Duracao total: {_formatar_duracao(total_execucao)}",
        "",
        "Resumo Geral",
        f"Processos planejados: {processos_planejados}",
        f"Processos concluidos: {processos_concluidos}",
        f"Processos com erro: {processos_erro}",
        f"Documentos listados: {docs_listados}",
        f"Documentos processados: {docs_processados}",
        f"Erros de documento/processo: {erros_documento}",
        f"EIA recuperados: {eias_total}",
        "",
        "Detalhamento por processo",
    ]

    for proc in processos_resumidos:
        linha = (
            f"- {proc['numero_processo']} | status={proc['status']} | "
            f"docs={proc['documentos_processados']}/{proc['documentos_listados']} | "
            f"eias={proc['eias_encontrados']} | "
            f"duracao={_formatar_duracao(proc['duracao_segundos'])}"
        )
        if proc.get("erro_processo"):
            linha += f" | erro={proc['erro_processo']}"
        linhas.append(linha)

    return "\n".join(linhas)


def main():
    # Carrega configuracoes locais padrao de ambiente quando houver.
    carregar_env_arquivo(".env")
    carregar_env_arquivo(".env.local")

    usuario = input("Usuario SEI: ")
    senha = input("Senha SEI: ")

    processos = obter_processos()
    if not processos:
        log("Nenhum processo carregado. Encerrando.")
        return

    headless = os.getenv("AGIL_HEADLESS", "1").strip() != "0"
    scraper = ScraperSEI(headless=headless)
    classificador = ClassificadorEIA(MODELO_CLASSIFICADOR)

    checkpoint = CheckpointExecucao()

    processos_pendentes = [
        processo
        for processo in processos
        if not checkpoint.processo_concluido(processo["numero_original"])
    ]

    if not processos_pendentes:
        log("Todos os processos ja constam como concluidos no checkpoint.")
        return

    if len(processos_pendentes) != len(processos):
        log(
            f"Retomada ativa: {len(processos) - len(processos_pendentes)} processo(s) "
            f"ja concluidos, {len(processos_pendentes)} pendente(s)."
        )

    inicio_execucao = datetime.now()
    resumo_processos = []

    try:
        log(f"Iniciando login no SEI (headless={headless})...")
        scraper.login(usuario, senha)

        total = len(processos_pendentes)
        for indice, processo in enumerate(processos_pendentes, start=1):
            resumo = processar_processo(
                scraper=scraper,
                classificador=classificador,
                processo=processo,
                indice=indice,
                total=total,
                checkpoint=checkpoint,
            )

            erro_timeout = (
                resumo.get("status") == "erro"
                and "TimeoutException" in (resumo.get("erro_processo") or "")
            )
            if erro_timeout:
                numero = processo.get("numero_original") or processo.get("numero_processo")
                log(
                    f"Timeout no processo {numero}. "
                    "Tentando relogin e nova tentativa unica..."
                )
                try:
                    scraper.login(usuario, senha)
                    resumo = processar_processo(
                        scraper=scraper,
                        classificador=classificador,
                        processo=processo,
                        indice=indice,
                        total=total,
                        checkpoint=checkpoint,
                    )
                except Exception as exc:
                    log(
                        f"Falha no relogin/retry do processo {numero}: "
                        f"{exc.__class__.__name__}: {exc}"
                    )

            resumo_processos.append(resumo)

        log("Execucao finalizada.")

    finally:
        scraper.fechar()
        fim_execucao = datetime.now()
        relatorio = montar_relatorio_execucao(
            inicio_execucao=inicio_execucao,
            fim_execucao=fim_execucao,
            processos_planejados=len(processos_pendentes),
            processos_resumidos=resumo_processos,
        )
        log("\n" + relatorio)
        try:
            assunto = (
                f"[AGIL] Execucao finalizada - "
                f"{fim_execucao.strftime('%Y-%m-%d %H:%M')}"
            )
            enviado, mensagem = enviar_relatorio_execucao(assunto, relatorio)
            if enviado:
                log(f"Relatorio por e-mail enviado: {mensagem}")
            else:
                log(f"Relatorio por e-mail nao enviado: {mensagem}")
        except Exception as exc:
            log(
                f"Falha inesperada ao enviar e-mail de relatorio: "
                f"{exc.__class__.__name__}: {exc}"
            )


if __name__ == "__main__":
    main()
