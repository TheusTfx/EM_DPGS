import os

NSC = "não consta na planilha"
PREFIXO_OBS = "Situação (planilha):"
SITUACOES = ['Aguardando', 'Empenhado', 'Pago', 'Cancelada']
STATUS_DEMANDAS = ['Enviado ao Estado', 'Retornada', 'Aprovada', 'Aguardando']

DATABASE_URL = os.environ.get('DATABASE_URL')

SESSION_DAYS = 7
