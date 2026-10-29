// ============================================================
// EMENDAS — listagem, filtros, ordenação, ficha, formulário
// Depende de: core.js
// ============================================================

// ---------- Listagem ----------
function debounceBusca() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(carregarEmendas, 300);
}

function marcarChips() {
  const v = $('filtro-parada').value;
  document.querySelectorAll('#chips-dias .chip').forEach(c =>
    c.classList.toggle('on', c.dataset.d === v));
}

function limparFiltros() {
  ['busca', 'filtro-situacao', 'filtro-ano', 'filtro-municipio',
   'filtro-secretaria', 'filtro-lider', 'filtro-regiao', 'filtro-parada']
    .forEach(id => { $(id).value = ''; });
  $('filtro-incompletos').checked = false;
  marcarChips();
  carregarEmendas();
}

async function carregarEmendas() {
  const p = new URLSearchParams();
  const add = (k, id) => { const v = $(id).value.trim(); if (v) p.append(k, v); };
  add('q', 'busca');
  add('situacao', 'filtro-situacao');
  add('ano', 'filtro-ano');
  add('municipio', 'filtro-municipio');
  add('secretaria', 'filtro-secretaria');
  add('lider', 'filtro-lider');
  add('regiao', 'filtro-regiao');
  add('parada_dias', 'filtro-parada');
  if ($('filtro-incompletos').checked) p.append('incompletos', '1');
  try {
    emendasCache = await api('/api/emendas?' + p);
    renderTabela();
    atualizarKPIs();
  } catch (err) {
    console.error(err);
    toast('Erro ao carregar emendas', 'error');
  }
}

async function carregarFiltros() {
  try {
    const f = await api('/api/filtros');
    const preencher = (id, rotulo, itens) => {
      const el = $(id), atual = el.value;
      el.innerHTML = '<option value="">' + rotulo + '</option>' +
        itens.map(s => '<option>' + escapeHTML(s) + '</option>').join('');
      if (itens.map(String).includes(atual)) el.value = atual;
    };
    preencher('filtro-situacao', 'Todas as situações', f.situacoes);
    preencher('filtro-ano', 'Todos os anos', f.anos);
    preencher('filtro-municipio', 'Todos os municípios', f.municipios);
    preencher('filtro-secretaria', 'Todas as secretarias', f.secretarias);
    preencher('filtro-lider', 'Todos os líderes', f.lideres);
    preencher('filtro-regiao', 'Todas as regiões', f.regioes);
    const pa = $('painel-ano'), cur = pa.value;
    pa.innerHTML = '<option value="">Todos os anos</option>' +
      f.anos.map(a => '<option>' + a + '</option>').join('');
    if (f.anos.map(String).includes(cur)) pa.value = cur;
  } catch (err) { console.error(err); }
}

function carregarTudo() {
  carregarEmendas();
  carregarFiltros();
}

function sortBy(col) {
  if (sortColumn === col) sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
  else { sortColumn = col; sortDirection = 'desc'; }
  document.querySelectorAll('thead th.sortable').forEach(th => {
    if (th.dataset.scope === 'dem') return;
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.sort === sortColumn) {
      th.classList.add(sortDirection === 'desc' ? 'sorted-desc' : 'sorted-asc');
    }
  });
  renderTabela();
}

function getListaOrdenada() {
  if (!sortColumn) return emendasCache;
  return [...emendasCache].sort((a, b) => {
    const va = a[sortColumn], vb = b[sortColumn];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return sortDirection === 'desc' ? vb - va : va - vb;
    }
    const sa = String(va).trim(), sb = String(vb).trim();
    if (/^\d+(\.\d+)?$/.test(sa) && /^\d+(\.\d+)?$/.test(sb)) {
      return sortDirection === 'desc'
        ? parseFloat(sb) - parseFloat(sa)
        : parseFloat(sa) - parseFloat(sb);
    }
    return sortDirection === 'desc'
      ? sb.toLowerCase().localeCompare(sa.toLowerCase(), 'pt-BR')
      : sa.toLowerCase().localeCompare(sb.toLowerCase(), 'pt-BR');
  });
}

function renderTabela() {
  const tbody = $('tbody'), lista = getListaOrdenada();
  $('contador').textContent = lista.length;
  $('contador-label').textContent = lista.length === 1 ? 'emenda' : 'emendas';
  $('tabela-wrap').hidden = lista.length === 0;
  $('empty').hidden = lista.length !== 0;
  tbody.innerHTML = '';
  lista.forEach(e => {
    const tr = document.createElement('tr');
    tr.addEventListener('click', () => abrirFicha(e.id));
    tr.innerHTML =
      '<td><div class="cell-main">' + escapeHTML(fmtNumero(e.numero_emenda)) + '</div><div class="cell-sub">' + escapeHTML(e.ano) + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(e.secretaria || '—') + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(e.municipio) + '</div><div class="cell-sub">' + escapeHTML(e.regiao || '—') + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(e.entidade || '—') + '</div><div class="cell-sub">' + escapeHTML(e.cnpj || '—') + '</div></td>' +
      '<td class="cell-obj" title="' + escapeHTML(e.objeto || '') + '"><div class="cell-main">' + escapeHTML(e.objeto || '—') + '</div></td>' +
      '<td class="cell-value">' + fmtMoney(e.valor_empenhado) + '<small>Pago: ' + fmtMoney(e.valor_pago) + '</small></td>' +
      '<td>' + badgeSituacao(e.situacao) + '</td>' +
      '<td class="right">' + (e.situacao_data ? fmtDataCurta(e.situacao_data) : '<span class="faint">—</span>') + '</td>' +
      '<td class="cell-actions"><div class="row-actions">' +
        '<button class="btn-icon" onclick="event.stopPropagation(); abrirModal(' + e.id + ')" title="Editar">' + icone(ICO_EDIT) + '</button>' +
        '<button class="btn-icon danger" onclick="event.stopPropagation(); excluirEmenda(' + e.id + ')" title="Excluir">' + icone(ICO_DEL) + '</button>' +
      '</div></td>';
    tbody.appendChild(tr);
  });
}

function atualizarKPIs() {
  $('kpi-total').textContent = emendasCache.length;
  $('kpi-valor').textContent = fmtMoney(emendasCache.reduce((s, e) => s + (Number(e.valor_empenhado) || 0), 0));
  $('kpi-pago').textContent = fmtMoney(emendasCache.reduce((s, e) => s + (Number(e.valor_pago) || 0), 0));
}

// ---------- Ficha ----------
async function abrirFichaPorId(id) {
  if (!emendasCache.find(x => x.id === id)) {
    try { emendasCache.push(await api('/api/emendas/' + id)); }
    catch (err) {
      toast('Emenda não encontrada (pode estar na lixeira)', 'error');
      return;
    }
  }
  abrirFicha(id);
}

async function abrirFicha(id) {
  const e = emendasCache.find(x => x.id === id);
  if (!e) return;
  fichaAtualId = id;
  $('ficha-titulo').textContent = 'Emenda nº ' + fmtNumero(e.numero_emenda);
  $('ficha-sub').textContent = 'Ano ' + (e.ano || '—') + ' · ' + (e.municipio || '—');
  const bruta = (e.situacao_bruta && e.situacao_bruta !== e.situacao)
    ? '<span style="font-size:12px;color:var(--muted);">Na planilha: ' + escapeHTML(e.situacao_bruta) + '</span>' : '';
  const nc = 'não consta na planilha';
  $('ficha-body').innerHTML =
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px;">' + badgeSituacao(e.situacao) +
      (e.dias_parada != null ? '<span style="font-size:12.5px;color:var(--muted);">sem movimento há ' + diasHTML(e.dias_parada) + '</span>' : '') + bruta + '</div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Identificação</div><div class="ficha-grid">' +
      campoFicha('Nº da emenda', fmtNumero(e.numero_emenda)) + campoFicha('Ano', e.ano) + campoFicha('Secretaria', e.secretaria, { vazio: nc }) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Localidade</div><div class="ficha-grid">' +
      campoFicha('Município', e.municipio) + campoFicha('Região', e.regiao, { vazio: nc }) + campoFicha('Líder', e.lider, { vazio: nc }) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Entidade beneficiária</div><div class="ficha-grid">' +
      campoFicha('Entidade', e.entidade, { vazio: nc }) + campoFicha('CNPJ', e.cnpj, { vazio: nc }) + campoFicha('Ofício', e.oficio, { vazio: nc }) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Contatos</div>' +
      '<div class="ficha-sub">Responsável</div><div class="ficha-grid" style="margin-bottom:12px;">' +
        campoFicha('Nome', e.resp_nome, { vazio: nc }) + campoFicha('Telefone', e.resp_contato, { vazio: nc }) + campoFicha('E-mail', e.resp_email, { vazio: nc }) + '</div>' +
      '<div class="ficha-sub">Ponto focal</div><div class="ficha-grid">' +
        campoFicha('Nome', e.pf_nome, { vazio: nc }) + campoFicha('Telefone', e.pf_contato, { vazio: nc }) + campoFicha('E-mail', e.pf_email, { vazio: nc }) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Detalhes</div>' +
      campoFicha('Objeto', e.objeto, { full: true, vazio: nc }) + campoFicha('Referência', e.referencia, { full: true, pre: true, vazio: nc }) +
      campoFicha('Justificativa', e.justificativa, { full: true, pre: true, vazio: nc }) +
      (e.observacoes ? campoFicha('Observações', e.observacoes, { full: true, pre: true }) : '') + '</div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Valores e prazos</div><div class="ficha-grid">' +
      '<div class="ficha-field"><label>Valor da emenda</label><div style="font-weight:600;">' + fmtMoney(e.valor_empenhado) + '</div></div>' +
      '<div class="ficha-field"><label>Valor pago</label><div style="font-weight:600;">' + fmtMoney(e.valor_pago) + '</div></div>' +
      campoFicha('Data da última atualização', e.situacao_data ? fmtDataCurta(e.situacao_data) : '') +
      campoFicha('Data de entrada', e.data_entrada ? fmtData(e.data_entrada) : '') +
      campoFicha('Data do pagamento', e.pago_em ? fmtData(e.pago_em) : '') + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Histórico</div><div class="hist-mini" id="ficha-hist"><span class="hint">Carregando...</span></div></div>';
  $('modal-ficha').classList.add('open');
  try {
    const r = await api('/api/logs?emenda_id=' + id + '&limite=15');
    $('ficha-hist').innerHTML = r.itens.length
      ? r.itens.map(l => logItemHTML(l, false)).join('')
      : '<span class="hint">Nenhuma alteração registrada.</span>';
  } catch (err) {
    $('ficha-hist').innerHTML = '<span class="hint">Não foi possível carregar o histórico.</span>';
  }
}

function fecharFicha() { $('modal-ficha').classList.remove('open'); }
function editarDaFicha() { const id = fichaAtualId; fecharFicha(); if (id) abrirModal(id); }
async function excluirDaFicha() {
  const id = fichaAtualId;
  if (id && await excluirEmenda(id)) fecharFicha();
}

// ---------- Formulário ----------
const CAMPOS_FORM = {
  'f-numero': 'numero_emenda', 'f-ano': 'ano', 'f-secretaria': 'secretaria',
  'f-municipio': 'municipio', 'f-regiao': 'regiao', 'f-lider': 'lider',
  'f-oficio': 'oficio', 'f-referencia': 'referencia', 'f-entidade': 'entidade',
  'f-cnpj': 'cnpj', 'f-resp-nome': 'resp_nome', 'f-resp-contato': 'resp_contato',
  'f-resp-email': 'resp_email', 'f-pf-nome': 'pf_nome', 'f-pf-contato': 'pf_contato',
  'f-pf-email': 'pf_email', 'f-objeto': 'objeto', 'f-justificativa': 'justificativa',
  'f-situacao': 'situacao', 'f-observacoes': 'observacoes',
  'f-data-entrada': 'data_entrada', 'f-pago-em': 'pago_em',
};

function abrirModal(id) {
  $('form-emenda').reset();
  $('f-id').value = '';
  $('f-versao').value = '';
  $('f-ano').value = new Date().getFullYear();
  $('modal-title').textContent = id ? 'Editar emenda' : 'Nova emenda';
  regiaoEditadaManualmente = false;
  if (id) {
    const e = emendasCache.find(x => x.id === id);
    if (e) {
      $('f-id').value = e.id;
      $('f-versao').value = e.versao || 1;
      Object.entries(CAMPOS_FORM).forEach(([el, campo]) => {
        $(el).value = (e[campo] == null || e[campo] === NSC)
          ? ''
          : String(e[campo]).slice(0, campo.includes('data') || campo === 'pago_em' ? 10 : undefined);
      });
      $('f-situacao').value = e.situacao || 'Aguardando';
      $('f-valor').value = e.valor_empenhado || '';
      $('f-pago').value = e.valor_pago || '';
      if (e.regiao && e.regiao !== NSC) regiaoEditadaManualmente = true;
    }
  }
  $('modal-overlay').classList.add('open');
  setTimeout(() => $('f-numero').focus(), 100);
}

function fecharModal() { $('modal-overlay').classList.remove('open'); }

async function salvarEmenda(ev) {
  ev.preventDefault();
  const btn = $('btn-salvar');
  if (btn.disabled) return;
  const id = $('f-id').value;
  const dados = {};
  Object.entries(CAMPOS_FORM).forEach(([el, campo]) => { dados[campo] = $(el).value.trim(); });
  dados.ano = parseInt(dados.ano);
  dados.valor_empenhado = parseFloat($('f-valor').value) || 0;
  dados.valor_pago = parseFloat($('f-pago').value) || 0;
  if (id) dados.versao = parseInt($('f-versao').value) || 1;
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  let sucesso = false, msg = 'Erro ao salvar emenda', tipo = 'error';
  try {
    await api(id ? '/api/emendas/' + id : '/api/emendas',
      { method: id ? 'PUT' : 'POST', json: dados });
    sucesso = true;
    msg = id ? 'Emenda atualizada' : 'Emenda criada';
    tipo = 'success';
  } catch (err) {
    msg = err.status === 409
      ? 'Esta emenda foi alterada por outro usuário. Recarregue a página.'
      : err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar';
  }
  if (sucesso) fecharModal();
  toast(msg, tipo);
  if (sucesso) carregarTudo();
}

async function excluirEmenda(id) {
  if (!confirm('Mover esta emenda para a lixeira? Ela poderá ser restaurada depois.')) return false;
  try {
    await api('/api/emendas/' + id, { method: 'DELETE' });
    toast('Emenda movida para a lixeira');
    carregarTudo();
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}
