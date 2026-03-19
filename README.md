# AGIL

Pipeline para consulta de processos no SEI, download de anexos, classificacao de EIA e persistencia em acervo local.

## Ambiente

```bash
cd /home/wpm/projects/agil
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Execucao principal

```bash
read -r -p "SEI usuario: " AGIL_SEI_USUARIO
read -r -s -p "SEI senha: " AGIL_SEI_SENHA
echo
export AGIL_SEI_USUARIO AGIL_SEI_SENHA
AGIL_HEADLESS=1 python -u run.py
```

Opcional para limitar lote:

```bash
read -r -p "SEI usuario: " AGIL_SEI_USUARIO
read -r -s -p "SEI senha: " AGIL_SEI_SENHA
echo
export AGIL_SEI_USUARIO AGIL_SEI_SENHA
AGIL_MAX_PROCESSOS=5 AGIL_HEADLESS=1 python -u run.py
```

## Execucao resiliente (recomendado)

Use bloqueio de suspensao + sessao resiliente para evitar perda de execucao por hibernacao/desligamento:

```bash
tmux new -s agil
read -r -p "SEI usuario: " AGIL_SEI_USUARIO
read -r -s -p "SEI senha: " AGIL_SEI_SENHA
echo
export AGIL_SEI_USUARIO AGIL_SEI_SENHA
systemd-inhibit --what=sleep:idle --why="AGIL em execucao" \
  env AGIL_HEADLESS=1 python -u run.py
```

Alternativas de monitoramento:

```bash
tail -f logs/run_*.log
```

Se houver queda/interrupcao:

1. Reabra a sessao e rode `run.py` novamente.
2. O checkpoint retomara os processos pendentes automaticamente.
3. Se a execucao anterior ficou em estado `running`, o sistema gera relatorio de interrupcao na inicializacao seguinte.

## Configuracao portatil de ambiente (.env)

Para replicar em qualquer maquina:

```bash
cp .env.example .env
```

Edite o `.env` com seus valores persistentes (principalmente `AGIL_EMAIL_PASSWORD` com App Password do Gmail).
Para reduzir exposicao de credenciais, `AGIL_SEI_USUARIO` e `AGIL_SEI_SENHA` devem ser informados por sessao (via `read` + `export` nos comandos acima), sem salvar senha em arquivo.
O `run.py` carrega `.env`/`.env.local` automaticamente no inicio da execucao.
O classificador analisa o texto completo extraido de cada documento (sem corte por caracteres).

## Checkpoint e estado de execucao

- `data/checkpoint_execucao.json`: retomada por processo/documento.
- `data/execution_state.json`: estado incremental da execucao atual.
- `data/execution_state_history/`: historico arquivado de execucoes finalizadas/interrompidas.
- `data/acompanhamento_execucoes.csv`: tabela acumulada por processo e por execucao (documentos listados, processados, EIA e tempo estimado humano).

## Publicacao no GitHub

Antes de subir:

1. Confirmar que nao ha credenciais hardcoded.
2. Revisar `git status`.
3. Validar que dados locais (`data/EIA`, `temporarios`, `dataset_candidatos`) nao serao versionados.

Fluxo sugerido:

```bash
git init
git add .
git commit -m "feat: pipeline SEI com checkpoint e classificacao EIA"
git branch -M main
git remote add origin <URL_DO_REPO>
git push -u origin main
```
