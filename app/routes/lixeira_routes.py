from datetime import datetime
import json as _json

from flask import Blueprint, jsonify
import psycopg2.errors
from psycopg2.extras import Json

from ..database import get_db
from ..auth import login_obrigatorio, admin_obrigatorio
from ..log import registrar_log

bp = Blueprint('lixeira', __name__, url_prefix='/api')


@bp.route('/lixeira', methods=['GET'])
@login_obrigatorio
def listar():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM lixeira ORDER BY id DESC')
        return jsonify([dict(r) for r in cur.fetchall()])


@bp.route('/lixeira/<int:lid>/restaurar', methods=['POST'])
@login_obrigatorio
def restaurar(lid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM lixeira WHERE id = %s', (lid,))
        item = cur.fetchone()
        if not item:
            return jsonify({'erro': 'Item não encontrado'}), 404
        dados = item['dados']
        cols = [c for c in dados.keys() if c != 'id']
        cols = [c for c in cols if c in (
            'numero_emenda', 'ano', 'municipio', 'objeto', 'valor_empenhado',
            'valor_pago', 'situacao', 'observacoes', 'versao', 'atualizado_por',
            'atualizado_em', 'secretaria', 'lider', 'oficio', 'referencia',
            'entidade', 'cnpj', 'regiao', 'numero_e', 'justificativa',
            'situacao_bruta', 'pago_em', 'data_entrada',
            'resp_nome', 'resp_contato', 'resp_email',
            'pf_nome', 'pf_contato', 'pf_email')]
        placeholders = ','.join(['%s'] * len(cols))
        vals = [dados.get(c) for c in cols]
        try:
            cur.execute(f'INSERT INTO emendas ({",".join(cols)}) VALUES ({placeholders})', vals)
            cur.execute('DELETE FROM lixeira WHERE id = %s', (lid,))
            db.commit()
        except psycopg2.errors.UniqueViolation:
            db.rollback()
            return jsonify({
                'erro': 'Já existe uma emenda ativa com o mesmo nº e ano. '
                        'Exclua ou renomeie antes de restaurar.'
            }), 409
        except Exception as e:
            db.rollback()
            return jsonify({'erro': str(e)}), 500
    registrar_log('restaurou', numero=dados.get('numero_emenda'),
                  municipio=dados.get('municipio'), ano=dados.get('ano'))
    return jsonify({'ok': True})


@bp.route('/lixeira/<int:lid>', methods=['DELETE'])
@admin_obrigatorio
def excluir_definitivo(lid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM lixeira WHERE id = %s', (lid,))
    db.commit()
    return jsonify({'ok': True})
