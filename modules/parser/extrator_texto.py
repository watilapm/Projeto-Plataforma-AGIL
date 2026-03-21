import os
import signal
import time
from pathlib import Path

import pdfplumber


def _mensagem_excecao_segura(exc: Exception, limite: int = 220):
    nome = exc.__class__.__name__
    args = getattr(exc, "args", ())
    if not args:
        return nome

    primeiro = args[0]
    if isinstance(primeiro, bytes):
        detalhe = f"bytes(len={len(primeiro)})"
    elif isinstance(primeiro, (str, int, float, bool)):
        detalhe = str(primeiro)
    else:
        return nome

    detalhe = detalhe.replace("\n", " ").replace("\r", " ").strip()
    if len(detalhe) > limite:
        detalhe = detalhe[: limite - 3] + "..."

    return f"{nome}: {detalhe}" if detalhe else nome


def _int_env(nome: str, padrao: int):
    valor = os.getenv(nome, "").strip()
    if not valor:
        return padrao
    try:
        return int(valor)
    except ValueError:
        return padrao


def _limite_mb_pdf():
    valor = os.getenv("AGIL_PDF_MAX_MB", "").strip()
    if not valor:
        return 0
    try:
        return max(0, int(valor))
    except ValueError:
        return 0


def _pdf_excede_limite(caminho_pdf):
    limite_mb = _limite_mb_pdf()
    if limite_mb <= 0:
        return False

    try:
        tamanho_bytes = Path(caminho_pdf).stat().st_size
    except Exception:
        return False

    return tamanho_bytes > (limite_mb * 1024 * 1024)


def _executar_com_timeout(segundos: int, func):
    segundos = max(0, int(segundos or 0))
    if segundos <= 0 or not hasattr(signal, "SIGALRM"):
        return func()

    handler_anterior = signal.getsignal(signal.SIGALRM)

    def _handler_timeout(_signum, _frame):
        raise TimeoutError("tempo_limite_de_extracao")

    try:
        signal.signal(signal.SIGALRM, _handler_timeout)
        signal.alarm(segundos)
        return func()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, handler_anterior)


def _extrair_texto_pagina_seguro(pagina, indice: int, caminho_pdf, timeout_pagina: int):
    try:
        return _executar_com_timeout(timeout_pagina, lambda: pagina.extract_text() or "")
    except TimeoutError:
        print(
            f"Timeout na extracao da pagina {indice} ({Path(caminho_pdf).name}). Pagina ignorada.",
            flush=True,
        )
        return ""
    except ValueError:
        # Fallback quando signal/alarm nao pode ser aplicado (thread secundaria, etc).
        try:
            return pagina.extract_text() or ""
        except Exception as exc:
            print(
                f"Falha na extracao de texto da pagina {indice} "
                f"({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
                flush=True,
            )
            return ""
    except Exception as exc:
        print(
            f"Falha na extracao de texto da pagina {indice} "
            f"({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
            flush=True,
        )
        return ""


def extrair_texto_e_paginas_pdf(caminho_pdf):

    texto = []
    paginas = []
    timeout_pagina = max(0, _int_env("AGIL_PDF_TIMEOUT_PAGINA", 7))

    try:
        if _pdf_excede_limite(caminho_pdf):
            print(
                f"Extracao ignorada: PDF acima do limite AGIL_PDF_MAX_MB ({Path(caminho_pdf).name})",
                flush=True,
            )
            return "", []

        with pdfplumber.open(caminho_pdf) as pdf:
            for indice, pagina in enumerate(pdf.pages, start=1):
                conteudo = _extrair_texto_pagina_seguro(
                    pagina,
                    indice=indice,
                    caminho_pdf=caminho_pdf,
                    timeout_pagina=timeout_pagina,
                )
                if conteudo:
                    texto.append(conteudo)

                paginas.append(
                    {
                        "numero_pagina": indice,
                        "texto": conteudo,
                    }
                )

    except Exception as exc:
        print(
            f"Erro ao extrair texto do PDF ({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
            flush=True,
        )

    return "\n".join(texto), paginas


def extrair_texto_pdf(caminho_pdf):
    texto, _ = extrair_texto_e_paginas_pdf(caminho_pdf)
    return texto


def extrair_paginas_pdf(caminho_pdf):
    _, paginas = extrair_texto_e_paginas_pdf(caminho_pdf)
    return paginas


def _indices_paginas_amostradas(total_paginas: int, paginas_bloco: int):

    if total_paginas <= 0:
        return []

    if total_paginas <= paginas_bloco * 3:
        return list(range(total_paginas))

    inicio = list(range(paginas_bloco))
    meio_centro = total_paginas // 2
    meio_inicio = max(0, meio_centro - paginas_bloco // 2)
    meio = list(range(meio_inicio, min(total_paginas, meio_inicio + paginas_bloco)))
    fim = list(range(max(0, total_paginas - paginas_bloco), total_paginas))

    indices = sorted(set(inicio + meio + fim))
    return indices


def extrair_texto_pdf_amostrado(caminho_pdf, paginas_bloco=10, limite_paginas=60):

    texto = []
    paginas = []
    timeout_pagina = max(0, _int_env("AGIL_PDF_TIMEOUT_PAGINA", 7))
    timeout_total = max(0, _int_env("AGIL_PDF_TIMEOUT_AMOSTRA", 120))
    inicio_extracao = time.monotonic()

    try:
        if _pdf_excede_limite(caminho_pdf):
            print(
                f"Extracao ignorada: PDF acima do limite AGIL_PDF_MAX_MB ({Path(caminho_pdf).name})",
                flush=True,
            )
            return "", []

        with pdfplumber.open(caminho_pdf) as pdf:
            total_paginas = len(pdf.pages)

            if total_paginas <= limite_paginas:
                indices = list(range(total_paginas))
            else:
                indices = _indices_paginas_amostradas(total_paginas, paginas_bloco)

            for indice in indices:
                if timeout_total and (time.monotonic() - inicio_extracao) >= timeout_total:
                    print(
                        f"Timeout total na extracao amostrada ({timeout_total}s) "
                        f"({Path(caminho_pdf).name}). Seguindo com texto parcial.",
                        flush=True,
                    )
                    break

                conteudo = _extrair_texto_pagina_seguro(
                    pdf.pages[indice],
                    indice=indice + 1,
                    caminho_pdf=caminho_pdf,
                    timeout_pagina=timeout_pagina,
                )
                if conteudo:
                    texto.append(conteudo)

                paginas.append(
                    {
                        "numero_pagina": indice + 1,
                        "texto": conteudo,
                    }
                )

    except Exception as exc:
        print(
            f"Erro ao extrair texto do PDF ({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
            flush=True,
        )

    return "\n".join(texto), paginas


def iterar_blocos_texto_pdf(caminho_pdf, paginas_por_bloco=24, max_blocos=0):

    paginas_por_bloco = max(1, int(paginas_por_bloco or 1))
    max_blocos = int(max_blocos or 0)
    timeout_pagina = max(0, _int_env("AGIL_PDF_TIMEOUT_PAGINA", 7))
    timeout_total = max(0, _int_env("AGIL_PDF_TIMEOUT_BLOCOS", 300))
    inicio_extracao = time.monotonic()

    try:
        if _pdf_excede_limite(caminho_pdf):
            print(
                f"Extracao ignorada: PDF acima do limite AGIL_PDF_MAX_MB ({Path(caminho_pdf).name})",
                flush=True,
            )
            return

        with pdfplumber.open(caminho_pdf) as pdf:
            buffer_texto = []
            buffer_paginas = []
            blocos_emitidos = 0

            for indice, pagina in enumerate(pdf.pages, start=1):
                if timeout_total and (time.monotonic() - inicio_extracao) >= timeout_total:
                    print(
                        f"Timeout total na extracao em blocos ({timeout_total}s) "
                        f"({Path(caminho_pdf).name}). Seguindo com blocos parciais.",
                        flush=True,
                    )
                    break

                conteudo = _extrair_texto_pagina_seguro(
                    pagina,
                    indice=indice,
                    caminho_pdf=caminho_pdf,
                    timeout_pagina=timeout_pagina,
                )
                if conteudo.strip():
                    buffer_texto.append(conteudo)
                buffer_paginas.append(indice)

                if len(buffer_paginas) >= paginas_por_bloco:
                    yield "\n".join(buffer_texto), list(buffer_paginas)
                    blocos_emitidos += 1
                    if max_blocos and blocos_emitidos >= max_blocos:
                        return
                    buffer_texto = []
                    buffer_paginas = []

            if buffer_paginas:
                yield "\n".join(buffer_texto), list(buffer_paginas)

    except Exception as exc:
        print(
            f"Erro ao extrair texto do PDF ({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
            flush=True,
        )
        return
