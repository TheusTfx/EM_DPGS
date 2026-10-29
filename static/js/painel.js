// ============================================================
// PAINEL — gráficos, donuts, cards do dashboard
// ATIVIDADE — logs de auditoria
// LIXEIRA — emendas excluídas
// Depende de: core.js
// ============================================================

// ---------- PAINEL ----------
function barras(lista, opts) {
  opts = opts || {};
  if (!lista || !lista.length) return '<div class="sem-dados">Sem dados para exibir.</div>';
  const campo = opts.campo || 'n', fmt = opts.fmt || (v => v);
  const max = Math.max.apply(null, lista.map(i => Number(i[campo]) || 0)) || 1;
  return lista.map(i => {
    const v = Number(i[campo]) || 0;
    return '<div class="bar-row"><div class="bar-label" title="' + escapeHTML(i.nome) + '">' + escapeHTML(i.nome) + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + Math.max(2, v / max * 100) + '%"></div></div>' +
      '<div class="bar-val">' + fmt(v, i) + '</div></div>';
  }).join('');
}

function donut(lista) {
  const cores = {
    Pago: 'var(--c-pago)', Aguardando: 'var(--c-aguardando)',
    Cancelada: 'var(--c-cancelada)', Empenhado: 'var(--c-empenhado)'
  };
  const total = lista.reduce((s, i) => s + i.n, 0);
  if (!total) return '<div class="sem-dados">Sem dados para exibir.</div>';
  const R = 42, C = 2 * Math.PI * R;
  let off = 0, arcos = '';
  lista.forEach(i => {
    const len = i.n / total * C;
    arcos += '<circle cx="60" cy="60" r="' + R + '" fill="none" stroke="' + (cores[i.nome] || '#aab') + '" stroke-width="16" stroke-dasharray="' + len + ' ' + (C - len) + '" stroke-dashoffset="' + (-off) + '" transform="rotate(-90 60 60)"/>';
    off += len;
  });
  const legenda = lista.map(i =>
    '<div><i style="background:' + (cores[i.nome] || '#aab') + '"></i><span><b>' + i.n + '</b> ' + escapeHTML(i.nome).toLowerCase() + ' <span class="faint">(' + Math.round(i.n / total * 100) + '% · ' + fmtMoneyCurto(i.valor) + ')</span></span></div>'
  ).join('');
  return '<div class="donut-wrap"><svg width="130" height="130" viewBox="0 0 120 120">' + arcos +
    '<text x="60" y="58" text-anchor="middle" font-size="20" font-weight="600" fill="currentColor">' + total + '</text>' +
    '<text x="60" y="73" text-anchor="middle" font-size="9" fill="var(--muted)">emendas</text></svg><div class="legend">' + legenda + '</div></div>';
}

function colunas(lista) {
  if (!lista || !lista.length) return '<div class="sem-dados">Ainda não há pagamentos com data registrada.</div>';
  const W = 520, H = 190, base = 150, topo = 24, n = lista.length, gap = 10;
  const bw = Math.min(46, (W - 20 - gap * (n - 1)) / n);
  const total = n * bw + (n - 1) * gap, x0 = (W - total) / 2;
  const max = Math.max.apply(null, lista.map(i => i.valor)) || 1;
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" style="max-height:210px"><line x1="0" y1="' + base + '" x2="' + W + '" y2="' + base + '" stroke="var(--border)"/>';
  lista.forEach((i, k) => {
    const h = Math.max(2, i.valor / max * (base - topo)), x = x0 + k * (bw + gap);
    const [a, m] = String(i.nome).split('-');
    svg += '<rect x="' + x + '" y="' + (base - h) + '" width="' + bw + '" height="' + h + '" fill="var(--accent)"/>' +
      '<text x="' + (x + bw / 2) + '" y="' + (base - h - 5) + '" text-anchor="middle" font-size="10" fill="var(--muted)">' + fmtMoneyCurto(i.valor).replace('R$ ', '') + '</text>' +
      '<text x="' + (x + bw / 2) + '" y="' + (base + 15) + '" text-anchor="middle" font-size="10.5" fill="var(--muted)">' + m + '/' + a.slice(2) + '</text>' +
      '<text x="' + (x + bw / 2) + '" y="' + (base + 28) + '" text-anchor="middle" font-size="10" fill="var(--faint)">' + i.n + ' emenda' + (i.n === 1 ? '' : 's') + '</text>';
  });
  return svg + '</svg>';
}

function cardRanking(chave, titulo, d) {
  const modo = painelModo[chave];
  const lista = d[chave + '_' + modo];
  const fmt = modo === 'n'
    ? (v, i) => v + ' <span class="faint">(' + i.pagas + ' pagas)</span>'
    : v => fmtMoneyCurto(v);
  return '<div class="card"><div class="card-head"><div class="card-title">' + titulo + '</div>' +
    '<div class="seg"><button class="' + (modo === 'n' ? 'on' : '') + '" onclick="trocarModo(\'' + chave + '\',\'n\')">Quantidade</button>' +
    '<button class="' + (modo === 'valor' ? 'on' : '') + '" onclick="trocarModo(\'' + chave + '\',\'valor\')">Valor</button></div></div>' +
    barras(lista, { campo: modo, fmt }) + '</div>';
}

function trocarModo(chave, modo) { painelModo[chave] = modo; renderPainel(); }

async function carregarPainel() {
  const ano = $('painel-ano').value;
  try {
    painelDados = await api('/api/estatisticas' + (ano ? '?ano=' + ano : ''));
    renderPainel();
  } catch (err) { toast(err.message, 'error'); }
}

function renderPainel() {
  const d = painelDados; if (!d) return;
  const r = d.resumo, t = d.tempo_pagamento;
  const pct = r.valor_total ? Math.round(r.valor_pago / r.valor_total * 100) : 0;
  $('painel-sub').textContent = $('painel-ano').value ? 'emendas de ' + $('painel-ano').value : 'todos os anos';
  $('painel-kpis').innerHTML =
    '<div class="kpi"><div class="kpi-label">Emendas</div><div class="kpi-value">' + r.total + '</div></div>' +
    '<div class="kpi"><div class="kpi-label">Valor total</div><div class="kpi-value small">' + fmtMoneyCurto(r.valor_total) + '</div></div>' +
    '<div class="kpi"><div class="kpi-label">Valor pago</div><div class="kpi-value small">' + fmtMoneyCurto(r.valor_pago) + '</div><div class="kpi-sub">' + pct + '% do total</div></div>' +
    '<div class="kpi"><div class="kpi-label">Em aberto</div><div class="kpi-value">' + r.aguardando + '</div><div class="kpi-sub">' + r.pagas + ' pagas</div></div>' +
    '<div class="kpi"><div class="kpi-label">Sem movimento 30+ dias</div><div class="kpi-value">' + r.paradas_30 + '</div></div>' +
    '<div class="kpi"><div class="kpi-label">Tempo médio até pagar</div><div class="kpi-value">' + (t.n ? Math.round(t.media) + ' dias' : '—') + '</div><div class="kpi-sub">' + (t.n ? 'base: ' + t.n + ' pagamentos' : 'sem datas ainda') + '</div></div>';

  const tempoHTML = t.n
    ? '<div class="big-nums"><div><div class="n">' + Math.round(t.media) + '</div><div class="l">dias em média</div></div>' +
      '<div><div class="n">' + Math.round(t.mediana) + '</div><div class="l">dias (mediana)</div></div>' +
      '<div><div class="n">' + t.minimo + ' – ' + t.maximo + '</div><div class="l">menor e maior prazo</div></div>' +
      '<div><div class="n">' + t.n + '</div><div class="l">pagamentos medidos</div></div></div>' +
      (d.tempo_secretaria.length ? '<div class="ficha-sub" style="margin-top:6px;">Média de dias por secretaria</div>' + barras(d.tempo_secretaria.map(i => ({ nome: i.nome, n: Math.round(i.media), q: i.n })), { campo: 'n', fmt: (v, i) => v + ' d <span class="faint">(' + i.q + ')</span>' }) : '')
    : '<div class="sem-dados">Ainda não há pagamentos com data registrada. O prazo é medido da data de entrada (ou do cadastro no sistema) até a data do pagamento. Ele passa a ser calculado conforme as emendas são pagas ou quando a data do pagamento é informada na emenda.</div>';

  $('painel-cards').innerHTML =
    '<div class="card"><div class="card-head"><div class="card-title">Situação das emendas</div></div>' + donut(d.por_situacao) + '</div>' +
    '<div class="card"><div class="card-head"><div class="card-title">Emendas em aberto por tempo sem movimento</div></div>' + barras(d.faixas_paradas, { campo: 'n' }) +
      '<div class="card-note">Conta a partir da última data citada na situação da planilha ou da última alteração feita no sistema.</div></div>' +
    cardRanking('lider', 'Quem mais lidera', d) + cardRanking('municipio', 'Para onde mais é enviado (município)', d) +
    cardRanking('regiao', 'Regiões', d) + cardRanking('secretaria', 'Secretarias', d) +
    '<div class="card"><div class="card-head"><div class="card-title">Objetos mais frequentes</div></div>' + barras(d.objeto_n, { campo: 'n' }) + '</div>' +
    '<div class="card"><div class="card-head"><div class="card-title">Tempo até o pagamento</div></div>' + tempoHTML + '</div>' +
    '<div class="card wide"><div class="card-head"><div class="card-title">Valor pago por mês</div></div>' + colunas(d.pagamentos_mes) + '</div>' +
    '<div class="card wide"><div class="card-head"><div class="card-title">Comparativo por ano</div></div>' +
      barras(d.por_ano.map(i => ({ nome: i.nome + ' — ' + i.n + ' emendas', valor: i.valor, pago: i.pago })), { campo: 'valor', fmt: (v, i) => fmtMoneyCurto(v) + ' <span class="faint">(pago ' + fmtMoneyCurto(i.pago) + ')</span>' }) + '</div>';
}

// ---------- ATIVIDADE ----------
const ROTULO_ACAO = {
  criou: 'Criação', editou: 'Edição', excluiu: 'Exclusão',
  restaurou: 'Restauração', importou: 'Importação',
  'regiões': 'Regiões', 'usuário': 'Usuários'
};

function logItemHTML(l, mostrarEmenda) {
  const mud = (l.mudancas || []).map(m =>
    '<div><b>' + escapeHTML(m.campo) + ':</b> ' +
    (m.de ? '<span class="de">' + escapeHTML(m.de) + '</span> → ' : '') +
    escapeHTML(m.para || '(vazio)') + '</div>'
  ).join('');

  let alvo = '';
  if (l.demanda_id) {
    alvo = (mostrarEmenda
      ? '<a onclick="abrirFichaDemandaPorId(' + l.demanda_id + ')">Demanda</a>'
      : 'Demanda');
    if (l.municipio) alvo += (alvo ? ' · ' : '') + escapeHTML(l.municipio);
    if (l.ano) alvo += ' · ' + l.ano;
  } else if (l.numero_emenda) {
    alvo = (l.emenda_id && mostrarEmenda
      ? '<a onclick="abrirFichaPorId(' + l.emenda_id + ')">Emenda ' + escapeHTML(fmtNumero(l.numero_emenda)) + '</a>'
      : 'Emenda ' + escapeHTML(fmtNumero(l.numero_emenda))) +
      (l.municipio ? ' · ' + escapeHTML(l.municipio) : '') +
      (l.ano ? ' · ' + l.ano : '');
  }

  const quando = '<div class="log-when">' + escapeHTML(fmtDataHora(l.criado_em)) +
    '<br><span class="log-who">' + escapeHTML(l.usuario || 'sistema') + '</span></div>';
  const corpo = '<div><div class="log-head"><span class="log-acao ' + escapeHTML(l.acao) + '">' +
    escapeHTML(ROTULO_ACAO[l.acao] || l.acao) + '</span>' +
    (mostrarEmenda ? alvo : '') +
    (l.detalhe ? (mostrarEmenda && alvo ? ' — ' : '') + escapeHTML(l.detalhe) : '') +
    '</div>' + (mud ? '<div class="log-mud">' + mud + '</div>' : '') + '</div>';
  return mostrarEmenda
    ? '<div class="log-item">' + quando + corpo + '</div>'
    : '<div class="log-item"><div class="log-when">' + escapeHTML(fmtDataHora(l.criado_em)) +
      ' · <span class="log-who">' + escapeHTML(l.usuario || 'sistema') + '</span></div>' +
      corpo + '</div>';
}

function debounceLogs() {
  clearTimeout(logTimer);
  logTimer = setTimeout(() => carregarLogs(true), 300);
}

async function carregarLogs(reiniciar) {
  if (reiniciar) { logsOffset = 0; $('log-list').innerHTML = ''; }
  const p = new URLSearchParams({ limite: 50, offset: logsOffset });
  if ($('log-busca').value.trim()) p.append('q', $('log-busca').value.trim());
  if ($('log-usuario').value) p.append('usuario', $('log-usuario').value);
  if ($('log-acao').value) p.append('acao', $('log-acao').value);
  try {
    const r = await api('/api/logs?' + p);
    const sel = $('log-usuario'), atual = sel.value;
    sel.innerHTML = '<option value="">Todos os usuários</option>' +
      r.usuarios.map(u => '<option>' + escapeHTML(u) + '</option>').join('');
    sel.value = atual;
    $('log-list').insertAdjacentHTML('beforeend', r.itens.map(l => logItemHTML(l, true)).join(''));
    logsOffset += r.itens.length;
    if (!$('log-list').children.length) {
      $('log-list').innerHTML = '<div class="empty"><div class="empty-title">Nenhuma atividade encontrada</div></div>';
    }
    $('log-mais').hidden = logsOffset >= r.total;
  } catch (err) { toast(err.message, 'error'); }
}

// ---------- LIXEIRA ----------
async function carregarLixeira() {
  try {
    const lista = await api('/api/lixeira');
    $('empty-lixeira').hidden = lista.length !== 0;
    $('tbody-lixeira').innerHTML = lista.map(i => {
      const d = i.dados || {};
      return '<tr style="cursor:default;"><td>' + escapeHTML(fmtDataHora(i.excluida_em)) + '</td><td>' + escapeHTML(i.excluida_por || '—') + '</td>' +
        '<td><div class="cell-main">' + escapeHTML(fmtNumero(d.numero_emenda)) + '</div><div class="cell-sub">' + escapeHTML(d.ano) + '</div></td>' +
        '<td>' + escapeHTML(d.municipio || '—') + '</td><td>' + escapeHTML(d.entidade || '—') + '</td>' +
        '<td class="cell-value">' + fmtMoney(d.valor_empenhado) + '</td>' +
        '<td class="right" style="white-space:nowrap;"><button class="btn btn-secondary btn-sm" onclick="restaurarItem(' + i.id + ')">Restaurar</button>' +
        (auth.admin ? ' <button class="btn btn-danger btn-sm" onclick="excluirDefinitivo(' + i.id + ')">Excluir definitivamente</button>' : '') + '</td></tr>';
    }).join('');
  } catch (err) { toast(err.message, 'error'); }
}

async function restaurarItem(id) {
  try {
    await api('/api/lixeira/' + id + '/restaurar', { method: 'POST' });
    toast('Emenda restaurada');
    carregarLixeira();
    carregarTudo();
  } catch (err) { toast(err.message, 'error'); }
}

async function excluirDefinitivo(id) {
  if (!confirm('Excluir definitivamente? Esta ação não pode ser desfeita.')) return;
  try {
    await api('/api/lixeira/' + id, { method: 'DELETE' });
    toast('Excluída definitivamente');
    carregarLixeira();
  } catch (err) { toast(err.message, 'error'); }
}
