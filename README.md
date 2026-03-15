# AGIL

Pipeline para consulta de processos no SEI, download de anexos, classificação de EIA e persistência em acervo local.

## Ambiente

```bash
cd /home/wpm/projects/agil
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Execução principal

```bash
AGIL_HEADLESS=1 python -u run.py
```

Opcional para limitar lote:

```bash
AGIL_MAX_PROCESSOS=5 AGIL_HEADLESS=1 python -u run.py
```

## Configuração portátil de ambiente (.env)

Para replicar em qualquer máquina:

```bash
cp .env.example .env
```

Edite o `.env` com seus valores (principalmente `AGIL_EMAIL_PASSWORD` com App Password do Gmail).
O `run.py` carrega `.env`/`.env.local` automaticamente no início da execução.

## Checkpoint de execução

O pipeline usa `data/checkpoint_execucao.json` para retomar de onde parou:

- pula processos já concluídos;
- retoma processo interrompido no próximo documento pendente.

## Publicação no GitHub

Antes de subir:

1. Confirmar que não há credenciais hardcoded.
2. Revisar `git status`.
3. Validar que dados locais (`data/EIA`, `temporarios`, `dataset_candidatos`) não serão versionados.

Fluxo sugerido:

```bash
git init
git add .
git commit -m "feat: pipeline SEI com checkpoint e classificação EIA"
git branch -M main
git remote add origin <URL_DO_REPO>
git push -u origin main
```
