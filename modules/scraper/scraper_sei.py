from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    ElementClickInterceptedException,
)

from config.settings import (
    SEI_URL,
    TEMP_DIR,
    TIMEOUT_PADRAO,
)
from pathlib import Path
import time
import re
import os
from urllib.request import Request, urlopen
from urllib.parse import unquote
from urllib.parse import urljoin


class ScraperSEI:

    def __init__(self, headless: bool = False):
        self.headless = headless
        # Timeouts especificos por documento para evitar travas longas em itens da arvore.
        self.doc_timeout_click = int(os.getenv("AGIL_DOC_TIMEOUT_CLICK", "8"))
        self.doc_timeout_visual = int(os.getenv("AGIL_DOC_TIMEOUT_VISUAL", "6"))
        self.doc_timeout_conteudo = int(os.getenv("AGIL_DOC_TIMEOUT_CONTEUDO", "4"))
        self.doc_tentativas = int(os.getenv("AGIL_DOC_TENTATIVAS", "2"))
        self.driver = self._iniciar_driver()

    # --------------------------------------------------

    def _iniciar_driver(self):

        chrome_options = Options()

        if self.headless:
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized")

        prefs = {
            "download.default_directory": str(TEMP_DIR.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        }

        chrome_options.add_experimental_option("prefs", prefs)

        driver = webdriver.Chrome(options=chrome_options)

        driver.set_page_load_timeout(TIMEOUT_PADRAO)

        return driver

    # --------------------------------------------------

    def login(self, usuario: str, senha: str):

        print("Abrindo SEI...")

        self.driver.get(SEI_URL)

        wait = WebDriverWait(self.driver, TIMEOUT_PADRAO)

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
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'ACESSAR')]")
            )
        )

        self.driver.execute_script("arguments[0].click();", botao_login)

        time.sleep(3)

        self._fechar_popup_se_existir()

        print("Login realizado.")

    # --------------------------------------------------

    def _fechar_popup_se_existir(self):

        try:

            print("Verificando popup institucional...")

            wait = WebDriverWait(self.driver, 5)

            botao_fechar = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(@class,'ui-dialog-titlebar-close')]")
                )
            )

            botao_fechar.click()

            print("Popup fechado.")

        except TimeoutException:

            print("Nenhum popup encontrado.")

    # --------------------------------------------------

    def buscar_processo(self, numero_processo: str):

        print(f"Buscando processo: {numero_processo}")

        wait = WebDriverWait(self.driver, TIMEOUT_PADRAO)

        campo_busca = wait.until(
            EC.presence_of_element_located((By.NAME, "txtPesquisaRapida"))
        )

        campo_busca.clear()
        campo_busca.send_keys(numero_processo)
        campo_busca.submit()

        wait.until(EC.presence_of_element_located((By.ID, "ifrArvore")))
        time.sleep(1.5)

    # --------------------------------------------------
    def expandir_arvore_documentos(self):

        print("Expandindo árvore de documentos...")

        try:
            WebDriverWait(self.driver, TIMEOUT_PADRAO).until(
                EC.frame_to_be_available_and_switch_to_it((By.ID, "ifrArvore"))
            )
        except TimeoutException:
            print("Iframe da árvore não encontrado.")
            return

        while True:

            try:
                # Alguns processos nao trazem title padrao "Abrir Pasta".
                botoes_expandir = self.driver.find_elements(
                    By.XPATH,
                    "//img[contains(@src,'plus.gif')]"
                )
            except StaleElementReferenceException:
                time.sleep(0.4)
                continue

            if not botoes_expandir:
                break

            print(f"{len(botoes_expandir)} pastas para expandir")

            botao = botoes_expandir[0]

            try:

                src_antes = botao.get_attribute("src") or ""
                titulo_antes = botao.get_attribute("title") or ""
                botao_id = (botao.get_attribute("id") or "").strip()
                ancora = None
                if botao_id:
                    try:
                        ancora = self.driver.find_element(By.ID, f"anc{botao_id}")
                    except NoSuchElementException:
                        ancora = None

                alvo_click = ancora if ancora is not None else botao
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});",
                    alvo_click
                )
                self.driver.execute_script(
                    "arguments[0].click();",
                    alvo_click
                )

                WebDriverWait(self.driver, 5).until(
                    lambda driver: (
                        botao.get_attribute("src") != src_antes
                        or (botao.get_attribute("title") or "") != titulo_antes
                    )
                )

            except (StaleElementReferenceException, NoSuchElementException, TimeoutException):
                time.sleep(0.3)

            time.sleep(0.5)

        print("Árvore expandida.")

        self.driver.switch_to.default_content()



    # --------------------------------------------------

    @staticmethod
    def _nome_estrutural_ou_placeholder(nome: str) -> bool:

        nome_limpo = (nome or "").strip().lower()
        if not nome_limpo:
            return True

        if nome_limpo in {"aguarde...", "anexo", "volume"}:
            return True

        if nome_limpo in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}:
            return True

        return False

    # --------------------------------------------------

    def listar_documentos(self):

        """
        Retorna lista de metadados de documentos do processo.
        """

        documentos = []

        self.expandir_arvore_documentos()

        for tentativa in range(4):
            try:
                self.driver.switch_to.default_content()
                WebDriverWait(self.driver, TIMEOUT_PADRAO).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "ifrArvore"))
                )

                elementos = self.driver.find_elements(
                    By.XPATH,
                    "//a[contains(@class,'infraArvoreNo') and normalize-space(.) != '']"
                )

                snapshots = []
                for el in elementos:
                    try:
                        snapshots.append(
                            {
                                "nome": el.text.strip(),
                                "href": (el.get_attribute("href") or "").strip(),
                                "titulo": (el.get_attribute("title") or "").strip(),
                                "onclick": (el.get_attribute("onclick") or "").strip(),
                                "element_id": (el.get_attribute("id") or "").strip(),
                                "y": round(el.location.get("y", 0), 1),
                                "x": round(el.location.get("x", 0), 1),
                            }
                        )
                    except StaleElementReferenceException:
                        continue

                snapshots.sort(key=lambda item: (item["y"], item["x"]))

                documentos = []
                for item in snapshots:
                    nome = item["nome"]
                    href = item["href"]
                    titulo = item["titulo"]
                    numero_sei = self._extrair_numero_documento(nome, href, titulo)

                    if nome and not self._nome_estrutural_ou_placeholder(nome):
                        documentos.append(
                            {
                                "nome": nome,
                                "numero_sei": numero_sei,
                                "link_arvore": urljoin(f"{SEI_URL}/", href) if href else "",
                                "href_bruto": href,
                                "onclick": item["onclick"],
                                "element_id": item["element_id"],
                            }
                        )

                break

            except (StaleElementReferenceException, TimeoutException):
                documentos = []
                time.sleep(0.5)
                if tentativa == 3:
                    raise

        print(f"{len(documentos)} documentos encontrados.")

        self.driver.switch_to.default_content()

        return documentos

    # --------------------------------------------------

    @staticmethod
    def _extrair_numero_documento(*valores):

        for valor in valores:
            texto = (valor or "").strip()
            if not texto:
                continue

            match = re.search(r"\b(\d{6,9})\b", texto)
            if match:
                return match.group(1)

        return ""

    # --------------------------------------------------

    @staticmethod
    def _xpath_literal(valor: str) -> str:

        if "'" not in valor:
            return f"'{valor}'"

        if '"' not in valor:
            return f'"{valor}"'

        partes = valor.split("'")
        return "concat(" + ", \"'\", ".join(f"'{p}'" for p in partes) + ")"

    # --------------------------------------------------

    @staticmethod
    def _assinatura_arquivos():
        return {
            (arquivo.name, arquivo.stat().st_size, int(arquivo.stat().st_mtime))
            for arquivo in Path(TEMP_DIR).glob("*")
            if arquivo.is_file()
        }

    # --------------------------------------------------

    @staticmethod
    def _aguardar_novo_download(assinatura_antes, timeout=30):

        inicio = time.time()

        while time.time() - inicio <= timeout:

            # Enquanto houver .crdownload, o Chrome ainda está baixando.
            if list(Path(TEMP_DIR).glob("*.crdownload")):
                time.sleep(0.4)
                continue

            arquivos_atuais = [
                arquivo for arquivo in Path(TEMP_DIR).glob("*")
                if arquivo.is_file()
            ]

            novos = []
            for arquivo in arquivos_atuais:
                assinatura = (
                    arquivo.name,
                    arquivo.stat().st_size,
                    int(arquivo.stat().st_mtime),
                )
                if assinatura not in assinatura_antes:
                    novos.append(arquivo)

            if novos:
                novos.sort(key=lambda x: x.stat().st_mtime)
                return novos[-1]

            time.sleep(0.4)

        return None

    # --------------------------------------------------

    def _aguardar_visualizacao_atualizar(self, src_anterior, timeout=None):

        def _mudou_src(driver):
            try:
                frame = driver.find_element(By.ID, "ifrVisualizacao")
                src_atual = frame.get_attribute("src") or ""
                return src_atual and src_atual != src_anterior
            except Exception:
                return False

        espera = timeout if timeout is not None else TIMEOUT_PADRAO
        WebDriverWait(self.driver, espera).until(_mudou_src)

    # --------------------------------------------------

    def _obter_url_download_visualizacao(self):

        seletores = [
            (By.XPATH, "//iframe[@id='ifrArvoreHtml' and @src]"),
            (By.XPATH, "//a[contains(normalize-space(.), 'Clique aqui') and @href]"),
            (By.XPATH, "//a[contains(@href, 'controlador.php') and @href]"),
            (By.XPATH, "//iframe[contains(@src, 'controlador.php') and @src]"),
            (By.XPATH, "//embed[@src]"),
            (By.XPATH, "//object[@data]"),
            (By.XPATH, "//iframe[@src]"),
        ]

        for by, seletor in seletores:
            elementos = self.driver.find_elements(by, seletor)
            for elemento in elementos:
                atributo = "data" if elemento.tag_name.lower() == "object" else "src"
                if elemento.tag_name.lower() == "a":
                    atributo = "href"

                url = (elemento.get_attribute(atributo) or "").strip()
                if url:
                    return url

        try:
            url_atual = self.driver.execute_script("return window.location.href;") or ""
        except Exception:
            url_atual = ""

        return url_atual.strip() or None

    # --------------------------------------------------

    @staticmethod
    def _sanitizar_nome_arquivo(nome: str) -> str:
        nome = re.sub(r"[\\\\/:*?\"<>|]+", "_", nome).strip()
        return nome[:180] or "documento"

    # --------------------------------------------------

    @staticmethod
    def _extrair_nome_resposta(content_disposition: str, fallback: str) -> str:

        if content_disposition:
            match_utf8 = re.search(
                r"filename\\*=UTF-8''([^;]+)",
                content_disposition,
                flags=re.IGNORECASE,
            )
            if match_utf8:
                return unquote(match_utf8.group(1).strip().strip('"'))

            match = re.search(
                r'filename="?([^";]+)"?',
                content_disposition,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()

        return fallback

    # --------------------------------------------------

    def _baixar_arquivo_com_sessao(self, url: str, nome_documento: str):

        url = urljoin(f"{SEI_URL}/", url)

        cookies = self.driver.get_cookies()
        cookie_header = "; ".join(
            f"{cookie['name']}={cookie['value']}" for cookie in cookies
        )

        req = Request(
            url,
            headers={
                "Cookie": cookie_header,
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
            },
        )

        with urlopen(req, timeout=TIMEOUT_PADRAO) as resp:
            conteudo = resp.read()
            content_type = (resp.headers.get("Content-Type") or "").lower()
            disposition = resp.headers.get("Content-Disposition") or ""

        if not conteudo:
            return None

        nome_fallback = self._sanitizar_nome_arquivo(nome_documento)
        nome_arquivo = self._extrair_nome_resposta(disposition, nome_fallback)
        nome_arquivo = self._sanitizar_nome_arquivo(nome_arquivo)

        if "." not in Path(nome_arquivo).name:
            if "pdf" in content_type:
                nome_arquivo += ".pdf"
            else:
                nome_arquivo += ".bin"

        destino = Path(TEMP_DIR) / nome_arquivo
        if destino.exists():
            destino = destino.with_name(
                f"{destino.stem}_{int(time.time())}{destino.suffix}"
            )

        destino.write_bytes(conteudo)
        return destino

    # --------------------------------------------------

    def baixar_documento(self, documento):

        """
        Encontra documento pelo nome e baixa.
        """

        nome_documento = (
            documento["nome"] if isinstance(documento, dict) else str(documento)
        )
        metadata = dict(documento) if isinstance(documento, dict) else {"nome": nome_documento}

        ultima_excecao = None

        for tentativa in range(max(1, self.doc_tentativas)):
            try:
                self.driver.switch_to.default_content()

                src_visualizacao_anterior = (
                    self.driver.find_element(By.ID, "ifrVisualizacao").get_attribute("src")
                    or ""
                )

                WebDriverWait(self.driver, self.doc_timeout_click).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "ifrArvore"))
                )

                wait = WebDriverWait(self.driver, self.doc_timeout_click)
                elemento = None

                href_bruto = metadata.get("href_bruto", "").strip()
                if href_bruto:
                    href_xpath = self._xpath_literal(href_bruto)
                    try:
                        elemento = wait.until(
                            EC.element_to_be_clickable(
                                (
                                    By.XPATH,
                                    f"//a[contains(@class,'infraArvoreNo') and @href = {href_xpath}]",
                                )
                            )
                        )
                    except TimeoutException:
                        elemento = None

                if elemento is None:
                    element_id = metadata.get("element_id", "").strip()
                    if element_id:
                        try:
                            elemento = wait.until(
                                EC.element_to_be_clickable((By.ID, element_id))
                            )
                        except TimeoutException:
                            elemento = None

                if elemento is None:
                    numero_sei = (metadata.get("numero_sei") or "").strip()
                    if numero_sei:
                        numero_xpath = self._xpath_literal(numero_sei)
                        xpath_numero = (
                            f"//a[contains(@class,'infraArvoreNo') and "
                            f"contains(normalize-space(.), {numero_xpath})]"
                        )
                        try:
                            elemento = wait.until(
                                EC.element_to_be_clickable((By.XPATH, xpath_numero))
                            )
                        except TimeoutException:
                            elemento = None

                if elemento is None:
                    nome_xpath = self._xpath_literal(nome_documento.strip())
                    xpath_link = (
                        f"//a[contains(@class,'infraArvoreNo') and "
                        f"normalize-space(.) = {nome_xpath}]"
                    )
                    elemento = wait.until(
                        EC.element_to_be_clickable((By.XPATH, xpath_link))
                    )

                self.driver.execute_script("arguments[0].click();", elemento)

                self.driver.switch_to.default_content()
                try:
                    self._aguardar_visualizacao_atualizar(
                        src_visualizacao_anterior,
                        timeout=self.doc_timeout_visual,
                    )
                except TimeoutException:
                    # Em alguns casos o SEI mantém o mesmo src e só atualiza conteúdo interno.
                    pass

                # O documento real fica no iframe de visualização.
                self.driver.switch_to.frame("ifrVisualizacao")
                try:
                    wait_vis = WebDriverWait(self.driver, max(2, self.doc_timeout_conteudo))
                    wait_vis.until(
                        lambda driver: (
                            driver.find_elements(By.XPATH, "//iframe[@id='ifrArvoreHtml' and @src]")
                            or driver.find_elements(
                                By.XPATH,
                                "//a[contains(normalize-space(.), 'Clique aqui') and @href]",
                            )
                            or driver.find_elements(
                                By.XPATH,
                                "//a[contains(@href, 'controlador.php') and @href]",
                            )
                            or driver.find_elements(
                                By.XPATH,
                                "//iframe[contains(@src, 'controlador.php') and @src]",
                            )
                            or driver.find_elements(By.XPATH, "//embed[@src]")
                            or driver.find_elements(By.XPATH, "//object[@data]")
                        )
                    )
                except TimeoutException:
                    pass

                url_download = self._obter_url_download_visualizacao() or ""
                if not url_download:
                    self.driver.switch_to.default_content()
                    return None

                self.driver.switch_to.default_content()
                arquivo = self._baixar_arquivo_com_sessao(url_download, nome_documento)

                if arquivo:
                    metadata["link_direto"] = urljoin(f"{SEI_URL}/", url_download)
                    metadata["arquivo"] = arquivo
                    return metadata

                return None

            except (
                TimeoutException,
                StaleElementReferenceException,
                NoSuchElementException,
                ElementClickInterceptedException,
            ) as exc:
                ultima_excecao = exc
                self.driver.switch_to.default_content()
                if isinstance(exc, TimeoutException):
                    try:
                        # Reconstroi a arvore quando o SEI perde estado apos muitos cliques.
                        self.expandir_arvore_documentos()
                    except Exception:
                        pass
                time.sleep(0.4)
                continue

            except Exception as exc:
                self.driver.switch_to.default_content()
                raise exc

        self.driver.switch_to.default_content()
        if ultima_excecao:
            raise ultima_excecao
        return None

    # --------------------------------------------------

    def fechar(self):

        print("Fechando navegador...")

        self.driver.quit()
