#!/usr/bin/env python

import os
import re
import signal
import zipfile
from getpass import getpass
from datetime import datetime
from time import monotonic, sleep
from uuid import uuid4

from modules.classifier.classificador import ClassificadorEIA
from modules.notifications.email_report import enviar_relatorio_execucao
from modules.parser.extrator_texto import extrair_texto_pdf_amostrado, iterar_blocos_texto_pdf
from modules.scraper.scraper_sei import ScraperSEI
from modules.storage.acompanhamento_execucoes import (
    registrar_acompanhamento_execucoes,
    sincronizar_acompanhamento_com_historico,
)
from modules.storage.checkpoint_execucao import CheckpointExecucao
from modules.storage.execution_state import ExecutionState
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


def documento_prioriza_reanalise_completa(documento, nome_analise="", texto_amostrado="", documento_idx=0, total_documentos=0):

    campos = [
        documento.get("nome", ""),
        documento.get("numero_sei", ""),
        documento.get("link_arvore", ""),
        nome_analise,
    ]
    texto_base = " ".join(normalizar_texto_regra(campo) for campo in campos if campo)

    termos_fortes = [
        "eia",
        "rima",
        "estudo de impacto ambiental",
        "impacto ambiental",
        "diagnostico ambiental",
        "estudo ambiental",
    ]
    for termo in termos_fortes:
        if termo in texto_base:
            return True, f"termo_forte:{termo}"

    termos_capitulo = [
        "diagnostico",
        "alternativas",
        "impactos",
        "medidas mitigadoras",
        "meio socioeconomico",
        "meio biotico",
        "meio fisico",
        "prognostico",
    ]
    if "capitulo" in texto_base:
        for termo in termos_capitulo:
            if termo in texto_base:
                return True, f"capitulo:{termo}"

    texto_amostra_norm = normalizar_texto_regra((texto_amostrado or "")[:12000])
    termos_amostra = [
        "estudo de impacto ambiental",
        "relatorio de impacto ambiental",
        "diagnostico ambiental",
        "meio socioeconomico",
        "meio biotico",
        "meio fisico",
    ]
    for termo in termos_amostra:
        if termo in texto_amostra_norm:
            return True, f"amostra:{termo}"

    tokens_estrutura = ["capitulo", "anexo", "volume", "diagnostico", "impactos", "alternativas"]
    if total_documentos >= 600 and documento_idx <= max(80, total_documentos // 5):
        if any(token in texto_base for token in tokens_estrutura):
            return True, "estrutura:processo_extenso_capitulo"

    if re.search(r"\bcap\.?\s*\d+\b", texto_base):
        return True, "estrutura:capitulo_numerado"

    return False, ""


def filtrar_texto_classificacao(texto: str):

    if not texto:
        return ""

    padrao_ruido_numerico = re.compile(r"^[\d\s\-_/.,:;()]+$")
    prefixos_descarte = (
        "figura",
        "fig.",
        "imagem",
        "ilustracao",
        "quadro",
        "tabela",
        "mapa",
        "grafico",
        "grafico",
        "foto",
        "fonte:",
    )

    linhas_filtradas = []
    for linha in (texto or "").splitlines():
        linha_limpa = " ".join((linha or "").split())
        if not linha_limpa:
            continue

        linha_norm = normalizar_texto_regra(linha_limpa)
        if linha_norm.startswith(prefixos_descarte):
            continue

        if padrao_ruido_numerico.fullmatch(linha_limpa):
            continue

        linhas_filtradas.append(linha_limpa)

    return "\n".join(linhas_filtradas)


def _int_env(nome: str, padrao: int):

    valor = os.getenv(nome, "").strip()
    if not valor:
        return padrao

    try:
        return int(valor)
    except ValueError:
        return padrao


def _erro_timeout(resumo: dict):
    return (
        resumo.get("status") == "erro"
        and "TimeoutException" in (resumo.get("erro_processo") or "")
    )


def _erro_tab_crashed(resumo: dict):
    erro = (resumo.get("erro_processo") or "").lower()
    return resumo.get("status") == "erro" and "tab crashed" in erro


def _erro_webdriver_conexao_recusada(resumo: dict):
    erro = (resumo.get("erro_processo") or "").lower()
    return (
        resumo.get("status") == "erro"
        and "maxretryerror" in erro
        and "httpconnectionpool(host='localhost'" in erro
        and "connection refused" in erro
    )


def _reiniciar_scraper_com_login(scraper, headless, usuario, senha):
    try:
        scraper.fechar()
    except Exception:
        pass

    novo_scraper = ScraperSEI(headless=headless)
    novo_scraper.login(usuario, senha)
    return novo_scraper


def _login_resiliente(scraper, headless, usuario, senha):
    tentativas = max(1, _int_env("AGIL_LOGIN_TENTATIVAS", 3))
    espera_retry = max(0, _int_env("AGIL_LOGIN_RETRY_SEGUNDOS", 2))

    ultimo_erro = None
    atual = scraper

    for tentativa in range(1, tentativas + 1):
        try:
            atual.login(usuario, senha)
            return atual
        except Exception as exc:
            ultimo_erro = exc
            log(
                f"Falha no login SEI (tentativa {tentativa}/{tentativas}): "
                f"{exc.__class__.__name__}: {exc}"
            )
            try:
                atual.fechar()
            except Exception:
                pass

            if tentativa < tentativas:
                if espera_retry:
                    sleep(espera_retry)
                atual = ScraperSEI(headless=headless)

    raise ultimo_erro


def reanalisar_documento_em_blocos(classificador, arquivo, numero_sei_atual):

    paginas_por_bloco = max(8, _int_env("AGIL_REANALISE_PAGINAS_BLOCO", 24))
    max_blocos = max(0, _int_env("AGIL_REANALISE_MAX_BLOCOS", 80))
    janela_chars = max(120000, _int_env("AGIL_REANALISE_JANELA_CHARS", 260000))

    blocos_analisados = 0
    texto_janela = ""

    for texto_bloco, paginas_bloco in iterar_blocos_texto_pdf(
        arquivo,
        paginas_por_bloco=paginas_por_bloco,
        max_blocos=max_blocos,
    ):
        texto_classificacao = filtrar_texto_classificacao(texto_bloco)
        if not texto_classificacao.strip():
            continue

        blocos_analisados += 1
        if numero_sei_atual == "sem_numero_sei":
            numero_sei_atual = extrair_numero_sei(texto_classificacao) or numero_sei_atual

        if classificador.prever(texto_classificacao) == 1:
            pagina_inicio = paginas_bloco[0] if paginas_bloco else 0
            pagina_fim = paginas_bloco[-1] if paginas_bloco else 0
            criterio = f"modelo_v4_reanalise_bloco:{pagina_inicio}-{pagina_fim}"
            return 1, criterio, numero_sei_atual, blocos_analisados

        texto_janela = (texto_janela + "\n" + texto_classificacao).strip()
        if len(texto_janela) > janela_chars:
            texto_janela = texto_janela[-janela_chars:]

        if blocos_analisados >= 2 and classificador.prever(texto_janela) == 1:
            pagina_inicio = paginas_bloco[0] if paginas_bloco else 0
            pagina_fim = paginas_bloco[-1] if paginas_bloco else 0
            criterio = f"modelo_v4_reanalise_janela:{pagina_inicio}-{pagina_fim}"
            return 1, criterio, numero_sei_atual, blocos_analisados

    return 0, "", numero_sei_atual, blocos_analisados


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
            texto, paginas_amostradas = extrair_texto_pdf_amostrado(
                arquivo,
                paginas_bloco=8,
                limite_paginas=80,
            )
            if not texto.strip():
                log(f"{prefixo_progresso}Arquivo sem texto extraido: {nome_analise}")
                continue

            numero_sei_final = numero_sei
            if numero_sei_final == "sem_numero_sei":
                numero_sei_final = extrair_numero_sei(texto) or numero_sei

            texto_classificacao = filtrar_texto_classificacao(texto)
            if not texto_classificacao.strip():
                log(
                    f"{prefixo_progresso}Texto util vazio apos filtro (figuras/tabelas): "
                    f"{nome_analise}"
                )
                continue

            criterio_classificacao = "modelo_v4_amostrado"
            resultado = classificador.prever(texto_classificacao)

            reanalisar_completo, motivo_reanalise = documento_prioriza_reanalise_completa(
                download,
                nome_analise,
                texto_classificacao,
                documento_idx=documento_idx,
                total_documentos=total_documentos,
            )
            if resultado != 1 and len(paginas_amostradas) >= 24 and reanalisar_completo:
                log(
                    f"{prefixo_progresso}Negativo na amostra; reanalisando por blocos "
                    f"(motivo='{motivo_reanalise}'): {nome_analise}"
                )
                resultado_bloco, criterio_bloco, numero_sei_final, blocos_analisados = reanalisar_documento_em_blocos(
                    classificador=classificador,
                    arquivo=arquivo,
                    numero_sei_atual=numero_sei_final,
                )
                if resultado_bloco == 1:
                    resultado = 1
                    criterio_classificacao = criterio_bloco
                    log(
                        f"{prefixo_progresso}EIA recuperado na reanalise por blocos "
                        f"({blocos_analisados} bloco(s) analisado(s)): {nome_analise}"
                    )
                else:
                    log(
                        f"{prefixo_progresso}Reanalise por blocos sem classificacao positiva "
                        f"apos {blocos_analisados} bloco(s): {nome_analise}"
                    )

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
        if isinstance(exc, TimeoutError):
            prefixo_erro = "Timeout ao baixar/ler anexo"
        elif isinstance(exc, zipfile.BadZipFile):
            prefixo_erro = "Falha ao abrir ZIP do documento"
        else:
            prefixo_erro = "Falha ao processar anexo compactado"

        log(
            f"{prefixo_erro} "
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




def _parse_datetime_iso(valor: str, fallback: datetime):
    if not valor:
        return fallback
    try:
        return datetime.fromisoformat(valor)
    except Exception:
        return fallback


def montar_relatorio_interrupcao(execucao_estado: dict, checkpoint: CheckpointExecucao):
    inicio = _parse_datetime_iso(execucao_estado.get("inicio_execucao", ""), datetime.now())
    heartbeat = _parse_datetime_iso(execucao_estado.get("heartbeat_em", ""), datetime.now())
    processos_planejados = int(execucao_estado.get("processos_planejados") or 0)
    processos_resumidos = list(execucao_estado.get("resumo_processos") or [])

    relatorio_base = montar_relatorio_execucao(
        inicio_execucao=inicio,
        fim_execucao=heartbeat,
        processos_planejados=processos_planejados,
        processos_resumidos=processos_resumidos,
    )

    interrupcao = execucao_estado.get("interrupcao") or {}
    processo_atual = checkpoint.estado.get("processo_atual") if hasattr(checkpoint, "estado") else None

    linhas = [
        "Relatorio de Interrupcao Detectada (execucao anterior)",
        f"Run ID: {execucao_estado.get('run_id', '')}",
        f"Status salvo: {execucao_estado.get('status', '')}",
        f"Inicio salvo: {execucao_estado.get('inicio_execucao', '')}",
        f"Heartbeat salvo: {execucao_estado.get('heartbeat_em', '')}",
        f"Motivo salvo: {interrupcao.get('motivo', '')}",
        f"Detalhe salvo: {interrupcao.get('detalhe', '')}",
        f"Tentativas de retry por timeout: {len(execucao_estado.get('timeout_retries') or [])}",
        "",
    ]

    if isinstance(processo_atual, dict):
        linhas.extend(
            [
                "Checkpoint (processo em andamento na ultima execucao):",
                f"- numero_original: {processo_atual.get('numero_original', '')}",
                f"- indice_processo: {processo_atual.get('indice_processo', '')}/{processo_atual.get('total_processos', '')}",
                f"- proximo_documento_idx: {processo_atual.get('proximo_documento_idx', '')}",
                f"- documento_atual: {processo_atual.get('documento_atual', '')}",
                "",
            ]
        )

    linhas.append(relatorio_base)
    return "\n".join(linhas)


def _instalar_handlers_sinal(execution_state: ExecutionState, resumo_processos: list):
    handlers_antigos = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    estado_sinal = {"recebido": False}

    def _handler(signum, _frame):
        nome_sinal = signal.Signals(signum).name
        if estado_sinal["recebido"]:
            raise KeyboardInterrupt(f"Sinal repetido recebido: {nome_sinal}")

        estado_sinal["recebido"] = True
        log(f"Sinal {nome_sinal} recebido. Salvando estado de interrupcao...")
        try:
            execution_state.marcar_interrompida(
                motivo=nome_sinal,
                detalhe="Sinal recebido durante execucao",
                processos_resumidos=resumo_processos,
            )
        except Exception as exc:
            log(
                f"Falha ao persistir estado apos sinal {nome_sinal}: "
                f"{exc.__class__.__name__}: {exc}"
            )

        raise KeyboardInterrupt(f"Sinal {nome_sinal} recebido")

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return handlers_antigos


def _restaurar_handlers_sinal(handlers_antigos: dict):
    for sig, handler in (handlers_antigos or {}).items():
        try:
            signal.signal(sig, handler)
        except Exception:
            pass


def _obter_credenciais_sei():
    usuario_env = os.getenv("AGIL_SEI_USUARIO", "").strip()
    senha_env = os.getenv("AGIL_SEI_SENHA", "").strip()

    if os.isatty(0):
        usuario = input("Usuario SEI: ").strip()
        senha = getpass("Senha SEI: ").strip()

        usuario = usuario or usuario_env
        senha = senha or senha_env

        if usuario and senha:
            return usuario, senha

        raise RuntimeError(
            "Credenciais SEI nao informadas. Preencha no terminal ou defina AGIL_SEI_USUARIO e AGIL_SEI_SENHA."
        )

    if usuario_env and senha_env:
        return usuario_env, senha_env

    raise RuntimeError(
        "Execucao sem TTY detectada. Defina AGIL_SEI_USUARIO e AGIL_SEI_SENHA no ambiente para rodar em nohup/tmux."
    )


def main():
    # Carrega configuracoes locais padrao de ambiente quando houver.
    carregar_env_arquivo(".env")
    carregar_env_arquivo(".env.local")

    checkpoint = CheckpointExecucao()
    execution_state = ExecutionState()

    try:
        total_historico = sincronizar_acompanhamento_com_historico()
        if total_historico:
            log(f"Acompanhamento sincronizado com historico: {total_historico} linha(s).")
    except Exception as exc:
        log(
            "Falha ao sincronizar acompanhamento com historico: "
            f"{exc.__class__.__name__}: {exc}"
        )

    estado_execucao_anterior = execution_state.obter_execucao_em_andamento()
    if estado_execucao_anterior:
        log(
            "Execucao anterior detectada como 'running'. "
            "Gerando relatorio parcial de interrupcao..."
        )
        relatorio_interrupcao = montar_relatorio_interrupcao(estado_execucao_anterior, checkpoint)
        log("\n" + relatorio_interrupcao)

        assunto_interrupcao = (
            "[AGIL] Execucao interrompida detectada - "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        try:
            enviado, mensagem = enviar_relatorio_execucao(assunto_interrupcao, relatorio_interrupcao)
            if enviado:
                log(f"Relatorio de interrupcao enviado: {mensagem}")
            else:
                log(f"Relatorio de interrupcao nao enviado: {mensagem}")
        except Exception as exc:
            log(
                "Falha inesperada ao enviar relatorio de interrupcao: "
                f"{exc.__class__.__name__}: {exc}"
            )

        try:
            total_registros = registrar_acompanhamento_execucoes(
                run_id=estado_execucao_anterior.get("run_id", ""),
                status_execucao="interrupted",
                inicio_execucao=estado_execucao_anterior.get("inicio_execucao", ""),
                fim_execucao=estado_execucao_anterior.get("heartbeat_em", ""),
                processos_planejados=int(estado_execucao_anterior.get("processos_planejados") or 0),
                processos_resumidos=estado_execucao_anterior.get("resumo_processos") or [],
                origem="detected_on_startup",
            )
            if total_registros:
                log(f"Acompanhamento atualizado com execucao anterior: {total_registros} linha(s).")
        except Exception as exc:
            log(
                "Falha ao registrar acompanhamento da execucao anterior: "
                f"{exc.__class__.__name__}: {exc}"
            )

        execution_state.marcar_interrompida(
            motivo="detected_on_startup",
            detalhe="Execucao anterior estava em running sem finalizacao limpa.",
            processos_resumidos=estado_execucao_anterior.get("resumo_processos", []),
        )
        execution_state.arquivar_e_limpar()

    processos = obter_processos()
    if not processos:
        log("Nenhum processo carregado. Encerrando.")
        return

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
    usuario, senha = _obter_credenciais_sei()

    headless = os.getenv("AGIL_HEADLESS", "1").strip() != "0"
    scraper = ScraperSEI(headless=headless)
    classificador = ClassificadorEIA(MODELO_CLASSIFICADOR)

    inicio_execucao = datetime.now()
    run_id = f"run_{inicio_execucao.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    resumo_processos = []

    execution_state.iniciar_execucao(
        run_id=run_id,
        inicio_execucao=inicio_execucao,
        processos_planejados=len(processos_pendentes),
    )

    handlers_antigos = {}
    execucao_finalizada = False
    interrompida = False

    try:
        handlers_antigos = _instalar_handlers_sinal(execution_state, resumo_processos)

        execution_state.registrar_heartbeat("antes_login")
        log(f"Iniciando login no SEI (headless={headless})...")
        scraper = _login_resiliente(scraper, headless, usuario, senha)

        total = len(processos_pendentes)
        reinicio_preventivo_cada = max(0, _int_env("AGIL_RESTART_BROWSER_CADA_PROCESSOS", 3))
        for indice, processo in enumerate(processos_pendentes, start=1):
            numero = processo.get("numero_original") or processo.get("numero_processo")
            execution_state.registrar_heartbeat(f"inicio_processo:{numero}")

            if reinicio_preventivo_cada and indice > 1 and (indice - 1) % reinicio_preventivo_cada == 0:
                log(
                    f"Reinicio preventivo do navegador antes do processo {numero} "
                    f"(a cada {reinicio_preventivo_cada} processo(s))."
                )
                try:
                    scraper = _reiniciar_scraper_com_login(scraper, headless, usuario, senha)
                except Exception as exc:
                    log(
                        "Falha no reinicio preventivo do navegador: "
                        f"{exc.__class__.__name__}: {exc}"
                    )

            resumo = processar_processo(
                scraper=scraper,
                classificador=classificador,
                processo=processo,
                indice=indice,
                total=total,
                checkpoint=checkpoint,
            )

            erro_timeout = _erro_timeout(resumo)
            erro_tab_crashed = _erro_tab_crashed(resumo)
            erro_webdriver_conexao = _erro_webdriver_conexao_recusada(resumo)
            if erro_timeout or erro_tab_crashed or erro_webdriver_conexao:
                if erro_timeout:
                    motivo_retry = "timeout"
                elif erro_tab_crashed:
                    motivo_retry = "tab_crashed"
                else:
                    motivo_retry = "webdriver_connection_refused"
                execution_state.registrar_evento_retry_timeout(
                    numero_processo=numero,
                    status="retry_iniciado",
                    detalhe=f"{motivo_retry}: {resumo.get('erro_processo') or ''}",
                )
                log(
                    f"Erro recuperavel no processo {numero} ({motivo_retry}). "
                    "Tentando nova tentativa unica..."
                )
                try:
                    execution_state.registrar_heartbeat(f"antes_retry:{numero}")
                    if erro_tab_crashed or erro_webdriver_conexao:
                        scraper = _reiniciar_scraper_com_login(scraper, headless, usuario, senha)
                    else:
                        scraper = _login_resiliente(scraper, headless, usuario, senha)

                    resumo = processar_processo(
                        scraper=scraper,
                        classificador=classificador,
                        processo=processo,
                        indice=indice,
                        total=total,
                        checkpoint=checkpoint,
                    )
                    status_retry = (
                        "retry_sucesso" if resumo.get("status") == "concluido" else "retry_sem_sucesso"
                    )
                    execution_state.registrar_evento_retry_timeout(
                        numero_processo=numero,
                        status=status_retry,
                        detalhe=resumo.get("erro_processo") or "",
                    )
                except Exception as exc:
                    execution_state.registrar_evento_retry_timeout(
                        numero_processo=numero,
                        status="retry_falha",
                        detalhe=f"{exc.__class__.__name__}: {exc}",
                    )
                    log(
                        f"Falha no relogin/retry do processo {numero}: "
                        f"{exc.__class__.__name__}: {exc}"
                    )

            resumo_processos.append(resumo)
            execution_state.atualizar_resumo_processos(
                resumo_processos,
                contexto=f"fim_processo:{numero}",
            )

        log("Execucao finalizada.")
        execucao_finalizada = True

    except KeyboardInterrupt as exc:
        interrompida = True
        motivo = str(exc) or "KeyboardInterrupt"
        log(f"Execucao interrompida: {motivo}")
        execution_state.marcar_interrompida(
            motivo="sinal_ou_interrupcao",
            detalhe=motivo,
            processos_resumidos=resumo_processos,
        )

    except Exception as exc:
        interrompida = True
        motivo = f"{exc.__class__.__name__}: {exc}"
        log(f"Falha inesperada no loop principal: {motivo}")
        execution_state.marcar_interrompida(
            motivo="erro_inesperado",
            detalhe=motivo,
            processos_resumidos=resumo_processos,
        )

    finally:
        _restaurar_handlers_sinal(handlers_antigos)
        scraper.fechar()

        fim_execucao = datetime.now()
        relatorio = montar_relatorio_execucao(
            inicio_execucao=inicio_execucao,
            fim_execucao=fim_execucao,
            processos_planejados=len(processos_pendentes),
            processos_resumidos=resumo_processos,
        )

        status_execucao = "finished" if execucao_finalizada and not interrompida else "interrupted"
        try:
            total_registros = registrar_acompanhamento_execucoes(
                run_id=run_id,
                status_execucao=status_execucao,
                inicio_execucao=inicio_execucao,
                fim_execucao=fim_execucao,
                processos_planejados=len(processos_pendentes),
                processos_resumidos=resumo_processos,
                origem="execucao_atual",
            )
            if total_registros:
                log(f"Tabela de acompanhamento atualizada: {total_registros} linha(s).")
        except Exception as exc:
            log(
                "Falha ao atualizar tabela de acompanhamento: "
                f"{exc.__class__.__name__}: {exc}"
            )

        if execucao_finalizada and not interrompida:
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

            execution_state.marcar_finalizada(resumo_processos)
            execution_state.arquivar_e_limpar()
        else:
            log("Execucao encerrada sem finalizacao completa. Relatorio parcial abaixo.")
            log("\n" + relatorio)
            estado_atual = execution_state.obter_estado()
            if (estado_atual.get("status") or "") != "interrupted":
                execution_state.marcar_interrompida(
                    motivo="encerramento_nao_finalizado",
                    detalhe="Execucao terminou sem estado final de sucesso.",
                    processos_resumidos=resumo_processos,
                )


if __name__ == "__main__":
    main()
