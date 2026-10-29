import json
from datetime import datetime
from psycopg2.extras import Json

from .database import get_db
from .auth import usuario_atual


def registrar_log(acao, emenda_id=None, demanda_id=None, numero=None,
                  municipio=None, ano=None, detalhe=None, mudancas=None):
    u = usuario_atual()
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''
                INSERT INTO logs (criado_em, usuario, acao, emenda_id, demanda_id,
                                  numero_emenda, municipio, ano, detalhe, mudancas)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (
                datetime.now().isoformat(timespec='seconds'),
                (u or {}).get('nome', 'sistema'),
                acao, emenda_id, demanda_id, numero, municipio,
                int(ano) if ano else None, detalhe,
                Json(mudancas or [],
                     dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False)),
            ))
        db.commit()
    except Exception as e:
        print('Erro registrando log:', e)
        db.rollback()
