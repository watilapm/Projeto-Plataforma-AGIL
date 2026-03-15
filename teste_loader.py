from modules.utils.loader_processos import carregar_processos

processos = carregar_processos("sislic-licencas.csv")

print("Processos carregados:", len(processos))

print(processos[0])