import json
from datetime import datetime
from pathlib import Path

from config.settings import CHECKPOINT_EXECUCAO


class CheckpointExecucao:

    def __init__(self, caminho: Path = CHECKPOINT_EXECUCAO):
        self.caminho = Path(caminho)
        self.estado = self._carregar()

    def _estado_base(self):
        return {
            "versao": 1,
            "atualizado_em": "",
            "processos_concluidos": [],
            "processo_atual": None,
        }

    def _carregar(self):
        if not self.caminho.exists():
            return self._estado_base()

        try:
            with open(self.caminho, encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except Exception:
            return self._estado_base()

        estado = self._estado_base()
        if isinstance(dados, dict):
            estado.update(dados)

        if not isinstance(estado.get("processos_concluidos"), list):
            estado["processos_concluidos"] = []

        return estado

    def _salvar(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.estado["atualizado_em"] = datetime.now().isoformat(timespec="seconds")

        temporario = self.caminho.with_suffix(".tmp")
        with open(temporario, "w", encoding="utf-8") as arquivo:
            json.dump(self.estado, arquivo, ensure_ascii=True, indent=2)
        temporario.replace(self.caminho)

    def processo_concluido(self, numero_original: str) -> bool:
        return numero_original in self.estado.get("processos_concluidos", [])

    def iniciar_processo(
        self,
        numero_original: str,
        empreendimento: str,
        indice_processo: int,
        total_processos: int,
        total_documentos: int,
        proximo_documento_idx: int = 0,
    ):
        self.estado["processo_atual"] = {
            "numero_original": numero_original,
            "empreendimento": empreendimento or "",
            "indice_processo": indice_processo,
            "total_processos": total_processos,
            "total_documentos": total_documentos,
            "proximo_documento_idx": max(0, int(proximo_documento_idx)),
            "documento_atual": "",
            "eias_encontrados": 0,
        }
        self._salvar()

    def obter_indice_retorno(self, numero_original: str) -> int:
        atual = self.estado.get("processo_atual")
        if not isinstance(atual, dict):
            return 0

        if atual.get("numero_original") != numero_original:
            return 0

        return max(0, int(atual.get("proximo_documento_idx", 0)))

    def marcar_documento_processado(self, numero_original: str, proximo_idx: int, nome_documento: str, eias: int):
        atual = self.estado.get("processo_atual")
        if not isinstance(atual, dict):
            return

        if atual.get("numero_original") != numero_original:
            return

        atual["proximo_documento_idx"] = max(0, int(proximo_idx))
        atual["documento_atual"] = nome_documento or ""
        atual["eias_encontrados"] = int(eias)
        self._salvar()

    def marcar_processo_concluido(self, numero_original: str):
        concluidos = self.estado.setdefault("processos_concluidos", [])
        if numero_original not in concluidos:
            concluidos.append(numero_original)

        atual = self.estado.get("processo_atual")
        if isinstance(atual, dict) and atual.get("numero_original") == numero_original:
            self.estado["processo_atual"] = None

        self._salvar()
