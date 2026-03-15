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


def extrair_texto_pdf_amostrado(caminho_pdf, paginas_bloco=10, limite_paginas=60):

    paginas = extrair_paginas_pdf(caminho_pdf)
    if not paginas:
        return "", paginas

    if len(paginas) <= limite_paginas:
        texto = "\n".join(pagina["texto"] for pagina in paginas if pagina["texto"].strip())
        return texto, paginas

    bloco_inicial = paginas[:paginas_bloco]
    meio = len(paginas) // 2
    inicio_meio = max(0, meio - paginas_bloco // 2)
    bloco_meio = paginas[inicio_meio: inicio_meio + paginas_bloco]
    bloco_final = paginas[-paginas_bloco:]

    paginas_selecionadas = []
    vistos = set()
    for bloco in (bloco_inicial, bloco_meio, bloco_final):
        for pagina in bloco:
            numero = pagina["numero_pagina"]
            if numero in vistos:
                continue
            vistos.add(numero)
            paginas_selecionadas.append(pagina)

    texto = "\n".join(
        pagina["texto"] for pagina in paginas_selecionadas if pagina["texto"].strip()
    )
    return texto, paginas_selecionadas
