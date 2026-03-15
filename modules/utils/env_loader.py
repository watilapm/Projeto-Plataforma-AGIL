from pathlib import Path


def carregar_env_arquivo(caminho_env: Path, sobrescrever: bool = True):
    """
    Carrega variaveis de ambiente de um arquivo .env (formato KEY=VALUE).
    Por padrao sobrescreve variaveis existentes no ambiente atual.
    """

    import os

    caminho = Path(caminho_env)
    if not caminho.exists():
        return False

    for linha in caminho.read_text(encoding="utf-8").splitlines():
        conteudo = linha.strip()
        if not conteudo or conteudo.startswith("#"):
            continue

        if "=" not in conteudo:
            continue

        chave, valor = conteudo.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip("'").strip('"')

        if not chave:
            continue

        if sobrescrever:
            os.environ[chave] = valor
        else:
            os.environ.setdefault(chave, valor)

    return True
