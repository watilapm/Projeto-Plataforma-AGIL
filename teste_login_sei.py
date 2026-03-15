from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SEI_URL = "https://sei.ibama.gov.br"


def teste_login(usuario, senha):

    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=chrome_options)

    wait = WebDriverWait(driver, 20)

    try:
        driver.get(SEI_URL)

        print("Abrindo SEI...")

        campo_usuario = wait.until(
            EC.visibility_of_element_located((By.ID, "txtUsuario"))
        )

        campo_senha = wait.until(
            EC.visibility_of_element_located((By.ID, "pwdSenha"))
        )

        campo_usuario.clear()
        campo_usuario.send_keys(usuario)

        campo_senha.clear()
        campo_senha.send_keys(senha)

        botao_login = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'ACESSAR')]"))
        )

        
        driver.execute_script("arguments[0].click();", botao_login)

        print("Login enviado.")

        input("Pressione ENTER para fechar o navegador")

    except Exception as e:

        print("Erro durante login:")
        print(e)

    finally:

        driver.quit()


if __name__ == "__main__":

    usuario = input("Usuário SEI: ")
    senha = input("Senha SEI: ")

    teste_login(usuario, senha)