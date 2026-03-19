import pdfplumber


def extrair_texto_e_paginas_pdf(caminho_pdf):

    texto = []
    paginas = []

    try:

        with pdfplumber.open(caminho_pdf) as pdf:

            for indice, pagina in enumerate(pdf.pages, start=1):

                conteudo = pagina.extract_text() or ""
                if conteudo:
                    texto.append(conteudo)

                paginas.append(
                    {
                        "numero_pagina": indice,
                        "texto": conteudo,
                    }
                )

    except Exception as e:

        print("Erro ao extrair texto do PDF:", e)

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

        with pdfplumber.open(caminho_pdf) as pdf:
            total_paginas = len(pdf.pages)

            if total_paginas <= limite_paginas:
                indices = list(range(total_paginas))
            else:
                indices = _indices_paginas_amostradas(total_paginas, paginas_bloco)

            for indice in indices:
                conteudo = pdf.pages[indice].extract_text() or ""
                if conteudo:
                    texto.append(conteudo)

                paginas.append(
                    {
                        "numero_pagina": indice + 1,
                        "texto": conteudo,
                    }
                )

    except Exception as e:

        print("Erro ao extrair texto do PDF:", e)

    return "\n".join(texto), paginas


def iterar_blocos_texto_pdf(caminho_pdf, paginas_por_bloco=24, max_blocos=0):

    paginas_por_bloco = max(1, int(paginas_por_bloco or 1))
    max_blocos = int(max_blocos or 0)

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            buffer_texto = []
            buffer_paginas = []
            blocos_emitidos = 0

            for indice, pagina in enumerate(pdf.pages, start=1):
                conteudo = pagina.extract_text() or ""
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

    except Exception as e:
        print("Erro ao extrair texto do PDF:", e)
        return
