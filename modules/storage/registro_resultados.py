import csv

from config.settings import CSV_RESULTADOS


CAMPOS_RESULTADO = [
    "numero_processo",
    "empreendimento",
    "numero_sei_documento",
    "nome_documento",
    "criterio_classificacao",
    "link_direto_sei",
    "caminho_pdf",
]


def garantir_csv_resultados():

    CSV_RESULTADOS.parent.mkdir(parents=True, exist_ok=True)

    if CSV_RESULTADOS.exists():
        with open(CSV_RESULTADOS, newline="", encoding="utf-8") as arquivo:
            leitor = csv.reader(arquivo)
            cabecalho = next(leitor, [])

        if cabecalho == CAMPOS_RESULTADO:
            return

        with open(CSV_RESULTADOS, newline="", encoding="utf-8") as arquivo:
            leitor = csv.DictReader(arquivo)
            linhas = list(leitor)

        with open(CSV_RESULTADOS, "w", newline="", encoding="utf-8") as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_RESULTADO)
            writer.writeheader()
            for linha in linhas:
                writer.writerow({campo: linha.get(campo, "") for campo in CAMPOS_RESULTADO})
        return

    with open(CSV_RESULTADOS, "w", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_RESULTADO)
        writer.writeheader()


def registrar_resultado(resultado: dict):

    garantir_csv_resultados()

    linha = {campo: resultado.get(campo, "") for campo in CAMPOS_RESULTADO}

    with open(CSV_RESULTADOS, "a", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_RESULTADO)
        writer.writerow(linha)
