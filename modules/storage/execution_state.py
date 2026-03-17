import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import EXECUTION_STATE_ARQUIVO, EXECUTION_STATE_HISTORICO_DIR


class ExecutionState:

    def __init__(
        self,
        caminho: Path = EXECUTION_STATE_ARQUIVO,
        historico_dir: Path = EXECUTION_STATE_HISTORICO_DIR,
    ):
        self.caminho = Path(caminho)
        self.historico_dir = Path(historico_dir)
        self.estado = self._carregar()

    def _estado_base(self):
        return {
            "versao": 1,
            "run_id": "",
            "inicio_execucao": "",
            "fim_execucao": "",
            "status": "",
            "processos_planejados": 0,
            "resumo_processos": [],
            "heartbeat_em": "",
            "heartbeat_contexto": "",
            "timeout_retries": [],
            "interrupcao": {"motivo": "", "detalhe": ""},
            "atualizado_em": "",
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

        if not isinstance(estado.get("resumo_processos"), list):
            estado["resumo_processos"] = []
        if not isinstance(estado.get("timeout_retries"), list):
            estado["timeout_retries"] = []
        if not isinstance(estado.get("interrupcao"), dict):
            estado["interrupcao"] = {"motivo": "", "detalhe": ""}

        return estado

    def _salvar(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.estado["atualizado_em"] = datetime.now().isoformat(timespec="seconds")

        temporario = self.caminho.with_suffix(".tmp")
        with open(temporario, "w", encoding="utf-8") as arquivo:
            json.dump(self.estado, arquivo, ensure_ascii=True, indent=2)
        temporario.replace(self.caminho)

    def obter_estado(self):
        return deepcopy(self.estado)

    def obter_execucao_em_andamento(self) -> Optional[dict]:
        status = (self.estado.get("status") or "").strip().lower()
        if status != "running":
            return None
        return self.obter_estado()

    def iniciar_execucao(self, run_id: str, inicio_execucao: datetime, processos_planejados: int):
        self.estado = self._estado_base()
        self.estado.update(
            {
                "run_id": run_id,
                "inicio_execucao": inicio_execucao.isoformat(timespec="seconds"),
                "status": "running",
                "processos_planejados": int(processos_planejados),
                "resumo_processos": [],
                "timeout_retries": [],
                "interrupcao": {"motivo": "", "detalhe": ""},
            }
        )
        self.registrar_heartbeat("inicio_execucao")

    def registrar_heartbeat(self, contexto: str = ""):
        self.estado["heartbeat_em"] = datetime.now().isoformat(timespec="seconds")
        self.estado["heartbeat_contexto"] = (contexto or "").strip()
        self._salvar()

    def atualizar_resumo_processos(self, processos_resumidos: list, contexto: str = "resumo_atualizado"):
        self.estado["resumo_processos"] = list(processos_resumidos or [])
        self.registrar_heartbeat(contexto)

    def registrar_evento_retry_timeout(self, numero_processo: str, status: str, detalhe: str = ""):
        self.estado.setdefault("timeout_retries", [])
        self.estado["timeout_retries"].append(
            {
                "quando": datetime.now().isoformat(timespec="seconds"),
                "numero_processo": numero_processo,
                "status": status,
                "detalhe": detalhe or "",
            }
        )
        self.registrar_heartbeat(f"retry_timeout:{status}")

    def marcar_interrompida(self, motivo: str, detalhe: str = "", processos_resumidos: Optional[list] = None):
        if processos_resumidos is not None:
            self.estado["resumo_processos"] = list(processos_resumidos)
        self.estado["status"] = "interrupted"
        self.estado["interrupcao"] = {
            "motivo": (motivo or "").strip(),
            "detalhe": (detalhe or "").strip(),
        }
        self.estado["fim_execucao"] = datetime.now().isoformat(timespec="seconds")
        self.registrar_heartbeat("interrompida")

    def marcar_finalizada(self, processos_resumidos: list):
        self.estado["status"] = "finished"
        self.estado["resumo_processos"] = list(processos_resumidos or [])
        self.estado["fim_execucao"] = datetime.now().isoformat(timespec="seconds")
        self.estado["interrupcao"] = {"motivo": "", "detalhe": ""}
        self.registrar_heartbeat("finalizada")

    def arquivar_e_limpar(self):
        estado_atual = self.obter_estado()
        run_id = (estado_atual.get("run_id") or "").strip()
        status = (estado_atual.get("status") or "").strip()
        if run_id and status:
            self.historico_dir.mkdir(parents=True, exist_ok=True)
            sufixo = datetime.now().strftime("%Y%m%d_%H%M%S")
            destino = self.historico_dir / f"{run_id}_{status}_{sufixo}.json"
            with open(destino, "w", encoding="utf-8") as arquivo:
                json.dump(estado_atual, arquivo, ensure_ascii=True, indent=2)

        self.estado = self._estado_base()
        self._salvar()
