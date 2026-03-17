import os

try:
    from joblib import load
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "Dependencia ausente: instale os requisitos do projeto com "
        "`python -m pip install -r requirements.txt`."
    ) from exc


class ClassificadorEIA:

    def __init__(self, caminho_modelo):

        print("Carregando modelo de classificação...")

        self.modelo = load(caminho_modelo)
        self.max_chars = int(os.getenv("AGIL_MAX_CHARS_CLASSIFICADOR", "250000"))

    def prever(self, texto):

        if not texto or len(texto.strip()) < 100:
            return 0

        texto_para_modelo = texto.strip()
        if self.max_chars > 0 and len(texto_para_modelo) > self.max_chars:
            texto_para_modelo = texto_para_modelo[: self.max_chars]

        resultado = self.modelo.predict([texto_para_modelo])[0]

        return resultado
