from modules.scraper.scraper_sei import ScraperSEI


def main():

    usuario = input("Usuário SEI: ")
    senha = input("Senha SEI: ")
    numero_processo = input("Número do processo: ")

    scraper = ScraperSEI(headless=False)

    try:

        print("\nIniciando login...")
        scraper.login(usuario, senha)

        print("\nBuscando processo...")
        scraper.buscar_processo(numero_processo)

        print("\nListando documentos...")
        documentos = scraper.listar_documentos()

        print("\nDocumentos encontrados:\n")

        for doc in documentos:
            print("-", doc["nome"])

    except Exception as e:

        print("\nErro durante execução:")
        print(e)

    finally:

        input("\nPressione ENTER para fechar o navegador...")
        scraper.fechar()


if __name__ == "__main__":
    main()