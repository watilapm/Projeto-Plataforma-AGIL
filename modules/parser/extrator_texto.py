import os
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


def extrair_texto_e_paginas_pdf(caminho_pdf):

    texto = []
    paginas = []

    try:
        if _pdf_excede_limite(caminho_pdf):
            print(
                f"Extracao ignorada: PDF acima do limite AGIL_PDF_MAX_MB ({Path(caminho_pdf).name})",
                flush=True,
            )
            return "", []

        with pdfplumber.open(caminho_pdf) as pdf:

            for indice, pagina in enumerate(pdf.pages, start=1):

                try:
                    conteudo = pagina.extract_text() or ""
                except Exception as exc:
                    print(
                        f"Falha na extracao de texto da pagina {indice} "
                        f"({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
                        flush=True,
                    )
                    conteudo = ""
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
                try:
                    conteudo = pdf.pages[indice].extract_text() or ""
                except Exception as exc:
                    print(
                        f"Falha na extracao de texto da pagina {indice + 1} "
                        f"({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
                        flush=True,
                    )
                    conteudo = ""
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
                try:
                    conteudo = pagina.extract_text() or ""
                except Exception as exc:
                    print(
                        f"Falha na extracao de texto da pagina {indice} "
                        f"({Path(caminho_pdf).name}): {_mensagem_excecao_segura(exc)}",
                        flush=True,
                    )
                    conteudo = ""
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
