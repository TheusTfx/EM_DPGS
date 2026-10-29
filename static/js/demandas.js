// ============================================================
// DEMANDAS — listagem, filtros, ordenação, ficha, formulário
// Depende de: core.js
// ============================================================

// ---------- Listagem ----------
function debounceBuscaDem() {
  clearTimeout(debounceTimerDem);
  debounceTimerDem = setTimeout(carregarDemandas, 300);
}

function limparFiltrosDem() {
  ['busca-dem', 'filtro-status-dem', 'filtro-ano-dem',
   'filtro-secretaria-dem', 'filtro-municipio-dem']
    .forEach(id => { $(id).value = ''; });
  carregarDemandas();
}

async function carregarDemandas() {
  const p = new URLSearchParams();
  const add = (k, id) => { const v = $(id).value.trim(); if (v) p.append(k, v); };
  add('q', 'busca-dem');
  add('status', 'filtro-status-dem');
  add('ano', 'filtro-ano-dem');
  add('secretaria', 'filtro-secretaria-dem');
  add('municipio', 'filtro-municipio-dem');
  try {
    demandasCache = await api('/api/demandas?' + p);
    renderTabelaDemandas();
    atualizarKPIsDemandas();
  } catch (err) {
    console.error(err);
    toast('Erro ao carregar demandas', 'error');
  }
}

async function carregarFiltrosDemandas() {
  try {
    const f = await api('/api/filtros-demandas');
    const preencher = (id, rotulo, itens) => {
      const el = $(id), atual = el.value;
      el.innerHTML = '<option value="">' + rotulo + '</option>' +
        itens.map(s => '<option>' + escapeHTML(s) + '</option>').join('');
      if (itens.map(String).includes(atual)) el.value = atual;
    };
    preencher('filtro-status-dem', 'Todos os status', f.status);
    preencher('filtro-ano-dem', 'Todos os anos', f.anos);
    preencher('filtro-secretaria-dem', 'Todas as secretarias', f.secretarias);
    preencher('filtro-municipio-dem', 'Todos os municípios', f.municipios);
  } catch (err) { console.error(err); }
}

function sortByDem(col) {
  if (sortColumnDem === col) sortDirectionDem = sortDirectionDem === 'desc' ? 'asc' : 'desc';
  else { sortColumnDem = col; sortDirectionDem = 'desc'; }
  document.querySelectorAll('th[data-scope="dem"].sortable').forEach(th => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.sort === sortColumnDem) {
      th.classList.add(sortDirectionDem === 'desc' ? 'sorted-desc' : 'sorted-asc');
    }
  });
  renderTabelaDemandas();
}

function getListaOrdenadaDem() {
  if (!sortColumnDem) return demandasCache;
  return [...demandasCache].sort((a, b) => {
    const va = a[sortColumnDem], vb = b[sortColumnDem];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return sortDirectionDem === 'desc' ? vb - va : va - vb;
    }
    const sa = String(va).trim(), sb = String(vb).trim();
    if (/^\d+(\.\d+)?$/.test(sa) && /^\d+(\.\d+)?$/.test(sb)) {
      return sortDirectionDem === 'desc'
        ? parseFloat(sb) - parseFloat(sa)
        : parseFloat(sa) - parseFloat(sb);
    }
    return sortDirectionDem === 'desc'
      ? sb.toLowerCase().localeCompare(sa.toLowerCase(), 'pt-BR')
      : sa.toLowerCase().localeCompare(sb.toLowerCase(), 'pt-BR');
  });
}

function renderTabelaDemandas() {
  const tbody = $('dem-tbody'), lista = getListaOrdenadaDem();
  $('dem-contador').textContent = lista.length;
  $('dem-contador-label').textContent = lista.length === 1 ? 'demanda' : 'demandas';
  $('dem-tabela-wrap').hidden = lista.length === 0;
  $('dem-empty').hidden = lista.length !== 0;
  tbody.innerHTML = '';
  lista.forEach(d => {
    const tr = document.createElement('tr');
    tr.addEventListener('click', () => abrirFichaDemanda(d.id));
    tr.innerHTML =
      '<td><div class="cell-main">' + escapeHTML(d.ano) + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(d.secretaria || '—') + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(d.municipio || '—') + '</div></td>' +
      '<td><div class="cell-main">' + escapeHTML(d.destinatario || '—') + '</div></td>' +
      '<td class="cell-obj" title="' + escapeHTML(d.objeto || '') + '"><div class="cell-main">' + escapeHTML(d.objeto || '—') + '</div></td>' +
      '<td class="cell-value">' + fmtMoney(d.valor) + '</td>' +
      '<td><div class="cell-main">' + escapeHTML(d.proposta_fpe || '—') + '</div></td>' +
      '<td>' + badgeStatusDemanda(d.status) + '</td>' +
      '<td class="cell-actions"><div class="row-actions">' +
        '<button class="btn-icon" onclick="event.stopPropagation(); abrirModalDemanda(' + d.id + ')" title="Editar">' + icone(ICO_EDIT) + '</button>' +
        '<button class="btn-icon danger" onclick="event.stopPropagation(); excluirDemanda(' + d.id + ')" title="Excluir">' + icone(ICO_DEL) + '</button>' +
      '</div></td>';
    tbody.appendChild(tr);
  });
}

function atualizarKPIsDemandas() {
  $('dem-kpi-total').textContent = demandasCache.length;
  $('dem-kpi-valor').textContent = fmtMoney(
    demandasCache.reduce((s, d) => s + (Number(d.valor) || 0), 0));
  const aprovadas = demandasCache.filter(d => d.status === 'Aprovada').length;
  $('dem-kpi-aprovadas').textContent = aprovadas;
}

// ---------- Ficha ----------
async function abrirFichaDemandaPorId(id) {
  if (!demandasCache.find(x => x.id === id)) {
    try { demandasCache.push(await api('/api/demandas/' + id)); }
    catch (err) {
      toast('Demanda não encontrada', 'error');
      return;
    }
  }
  abrirFichaDemanda(id);
}

async function abrirFichaDemanda(id) {
  const d = demandasCache.find(x => x.id === id);
  if (!d) return;
  fichaAtualDemandaId = id;
  $('dem-ficha-titulo').textContent = 'Demanda ' + (d.ano || '');
  $('dem-ficha-sub').textContent = (d.secretaria || '—')
    + ' · ' + (d.municipio || '—')
    + (d.destinatario ? ' · ' + d.destinatario : '');
  $('dem-ficha-body').innerHTML =
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px;">' +
      badgeStatusDemanda(d.status) + '</div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Identificação</div><div class="ficha-grid">' +
      campoFicha('Ano', d.ano) +
      campoFicha('Secretaria', d.secretaria) +
      campoFicha('Status', d.status) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Localidade</div><div class="ficha-grid">' +
      campoFicha('Município', d.municipio) +
      campoFicha('Destinatário', d.destinatario, { full: true }) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Objeto e valores</div><div class="ficha-grid">' +
      campoFicha('Objeto', d.objeto, { full: true }) +
      '<div class="ficha-field"><label>Valor</label><div style="font-weight:600;">' + fmtMoney(d.valor) + '</div></div>' +
      campoFicha('Proposta FPE', d.proposta_fpe) + '</div></div>' +
    '<div class="ficha-section"><div class="ficha-section-title">Documentos e pagamento</div><div class="ficha-grid">' +
      campoFicha('Convênio', d.convenio) +
      campoFicha('PROA / SEI', d.proa_sei) +
      campoFicha('Data do pagamento', d.data_pagto ? fmtData(d.data_pagto) : '') + '</div></div>' +
    (d.observacoes
      ? '<div class="ficha-section"><div class="ficha-section-title">Observações</div>' +
        campoFicha('', d.observacoes, { full: true, pre: true }) + '</div>'
      : '') +
    '<div class="ficha-section"><div class="ficha-section-title">Histórico</div>' +
      '<div class="hist-mini" id="dem-ficha-hist"><span class="hint">Carregando...</span></div></div>';
  $('modal-ficha-demanda').classList.add('open');
  try {
    const r = await api('/api/logs?demanda_id=' + id + '&limite=15');
    $('dem-ficha-hist').innerHTML = r.itens.length
      ? r.itens.map(l => logItemHTML(l, false)).join('')
      : '<span class="hint">Nenhuma alteração registrada.</span>';
  } catch (err) {
    $('dem-ficha-hist').innerHTML = '<span class="hint">Não foi possível carregar o histórico.</span>';
  }
}

function fecharFichaDemanda() { $('modal-ficha-demanda').classList.remove('open'); }
function editarDaFichaDemanda() {
  const id = fichaAtualDemandaId;
  fecharFichaDemanda();
  if (id) abrirModalDemanda(id);
}
async function excluirDaFichaDemanda() {
  const id = fichaAtualDemandaId;
  if (id && await excluirDemanda(id)) fecharFichaDemanda();
}

// ---------- Formulário ----------
const CAMPOS_FORM_DEM = {
  'd-ano': 'ano',
  'd-secretaria': 'secretaria',
  'd-municipio': 'municipio',
  'd-destinatario': 'destinatario',
  'd-objeto': 'objeto',
  'd-proposta-fpe': 'proposta_fpe',
  'd-status': 'status',
  'd-observacoes': 'observacoes',
  'd-convenio': 'convenio',
  'd-proa-sei': 'proa_sei',
  'd-data-pagto': 'data_pagto',
};

function abrirModalDemanda(id) {
  $('form-demanda').reset();
  $('d-id').value = '';
  $('d-versao').value = '';
  $('d-ano').value = new Date().getFullYear();
  $('d-status').value = 'Aguardando';
  $('modal-demanda-title').textContent = id ? 'Editar demanda' : 'Nova demanda';
  if (id) {
    const d = demandasCache.find(x => x.id === id);
    if (d) {
      $('d-id').value = d.id;
      $('d-versao').value = d.versao || 1;
      Object.entries(CAMPOS_FORM_DEM).forEach(([el, campo]) => {
        $(el).value = (d[campo] == null)
          ? ''
          : String(d[campo]).slice(0, campo === 'data_pagto' ? 10 : undefined);
      });
      $('d-valor').value = d.valor || '';
      $('d-status').value = d.status || 'Aguardando';
    }
  }
  $('modal-demanda').classList.add('open');
  setTimeout(() => $('d-ano').focus(), 100);
}

function fecharModalDemanda() { $('modal-demanda').classList.remove('open'); }

async function salvarDemanda(ev) {
  ev.preventDefault();
  const btn = $('btn-salvar-dem');
  if (btn.disabled) return;
  const id = $('d-id').value;
  const dados = {};
  Object.entries(CAMPOS_FORM_DEM).forEach(([el, campo]) => {
    dados[campo] = $(el).value.trim();
  });
  dados.ano = parseInt(dados.ano);
  dados.valor = parseFloat($('d-valor').value) || 0;
  if (id) dados.versao = parseInt($('d-versao').value) || 1;
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  let sucesso = false, msg = 'Erro ao salvar demanda', tipo = 'error';
  try {
    await api(id ? '/api/demandas/' + id : '/api/demandas',
      { method: id ? 'PUT' : 'POST', json: dados });
    sucesso = true;
    msg = id ? 'Demanda atualizada' : 'Demanda criada';
    tipo = 'success';
  } catch (err) {
    msg = err.status === 409
      ? 'Esta demanda foi alterada por outro usuário. Recarregue a página.'
      : err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar';
  }
  if (sucesso) fecharModalDemanda();
  toast(msg, tipo);
  if (sucesso) {
    carregarDemandas();
    carregarFiltrosDemandas();
  }
}

async function excluirDemanda(id) {
  if (!confirm('Excluir esta demanda? Esta ação não pode ser desfeita.')) return false;
  try {
    await api('/api/demandas/' + id, { method: 'DELETE' });
    toast('Demanda excluída');
    carregarDemandas();
    carregarFiltrosDemandas();
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}
