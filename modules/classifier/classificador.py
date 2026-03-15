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

    def prever(self, texto):

        if not texto or len(texto.strip()) < 100:
            return 0

        resultado = self.modelo.predict([texto])[0]

        return resultado
