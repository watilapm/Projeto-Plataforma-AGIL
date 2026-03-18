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
        self.chunk_overlap = int(os.getenv("AGIL_CLASSIFICADOR_CHUNK_OVERLAP", "10000"))

    def _iterar_chunks(self, texto: str):

        if self.max_chars <= 0:
            yield texto
            return

        if len(texto) <= self.max_chars:
            yield texto
            return

        overlap = max(0, self.chunk_overlap)
        passo = self.max_chars - overlap
        if passo <= 0:
            passo = self.max_chars

        for inicio in range(0, len(texto), passo):
            trecho = texto[inicio : inicio + self.max_chars]
            if len(trecho.strip()) >= 100:
                yield trecho
            if inicio + self.max_chars >= len(texto):
                break

    def prever(self, texto):

        if not texto or len(texto.strip()) < 100:
            return 0

        texto_para_modelo = texto.strip()

        for trecho in self._iterar_chunks(texto_para_modelo):
            resultado = self.modelo.predict([trecho])[0]
            if resultado == 1:
                return 1

        return 0
