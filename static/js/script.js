// ============================================================
// CONFIGURAÇÃO E ESTADO
// ============================================================
const NOME_SISTEMA = 'Controle de Emendas';
const NSC = 'não consta na planilha';
const CHAVE_AUTH = 'emendas_auth';

let auth = null;
let emendasCache = [];
let demandasCache = [];
let debounceTimer = null, logTimer = null, debounceTimerDem = null;
let sortColumn = null, sortDirection = 'desc';
let sortColumnDem = null, sortDirectionDem = 'desc';
let fichaAtualId = null;
let fichaAtualDemandaId = null;
let regiaoEditadaManualmente = false;
let regioesMap = {};
let previewOk = false;
let logsOffset = 0;
let painelDados = null;
const painelModo = { lider: 'n', municipio: 'n', regiao: 'n', secretaria: 'n' };

// ============================================================
// UTILITÁRIOS
// ============================================================
const $ = id => document.getElementById(id);

function fmtMoney(v) {
  return 'R$ ' + (Number(v) || 0).toLocaleString('pt-BR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtMoneyCurto(v) {
  v = Number(v) || 0;
  if (v >= 1e6) return 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' mi';
  if (v >= 1e3) return 'R$ ' + (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' mil';
  return 'R$ ' + v.toLocaleString('pt-BR');
}
function escapeHTML(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
function fmtNumero(n) { return String(n || '').startsWith('S/N-') ? NSC : (n || '—'); }
function fmtData(d) {
  if (!d) return '—';
  const p = String(d).slice(0, 10).split('-');
  return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : d;
}
function fmtDataCurta(d) {
  if (!d) return '—';
  const p = String(d).slice(0, 10).split('-');
  return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0].slice(2) : d;
}
function fmtDataHora(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('pt-BR',
    { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit',
      year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function chaveMun(s) {
  return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toUpperCase().replace(/\s+/g, ' ').trim();
}
function badgeSituacao(s) {
  const cls = (s || 'Aguardando').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
  return '<span class="status status-' + cls + '">' + escapeHTML(s || 'Aguardando') + '</span>';
}
function badgeStatusDemanda(s) {
  const cls = (s || 'Aguardando').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
  return '<span class="status status-' + cls + '">' + escapeHTML(s || 'Aguardando') + '</span>';
}
function diasHTML(d) {
  if (d == null) return '<span class="faint">—</span>';
  const cls = d >= 60 ? 'critico' : d >= 30 ? 'alerta' : '';
  return '<span class="dias ' + cls + '">' + d + (d === 1 ? ' dia' : ' dias') + '</span>';
}
function icone(path) {
  return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
}
const ICO_EDIT = '<path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>';
const ICO_DEL = '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>';

function toast(msg, tipo) {
  const el = $('toast');
  $('toast-msg').textContent = msg;
  el.className = 'toast show toast-' + (tipo || 'success');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3800);
}

// ============================================================
// API
// ============================================================
async function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign({}, opts.headers || {});
  if (auth && auth.token) headers['Authorization'] = 'Bearer ' + auth.token;
  const init = { method: opts.method || 'GET', headers };
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.json);
  } else if (opts.body) {
    init.body = opts.body;
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (res.status === 401 && path !== '/api/login') {
    sair(true);
    throw new Error('Sessão expirada. Entre novamente.');
  }
  if (!res.ok) {
    const err = new Error((data && data.erro) || ('Erro ' + res.status));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// ============================================================
// AUTENTICAÇÃO
// ============================================================
function mostrarLogin() {
  $('app').hidden = true;
  $('login-screen').hidden = false;
  $('l-senha').value = '';
  setTimeout(() => $('l-usuario').focus(), 50);
}

async function entrar(ev) {
  ev.preventDefault();
  const btn = $('l-btn');
  btn.disabled = true;
  $('l-erro').textContent = '';
  try {
    const d = await api('/api/login', {
      method: 'POST',
      json: { usuario: $('l-usuario').value, senha: $('l-senha').value }
    });
    auth = d;
    localStorage.setItem(CHAVE_AUTH, JSON.stringify(d));
    iniciarApp();
  } catch (err) {
    $('l-erro').textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

function sair(expirou) {
  localStorage.removeItem(CHAVE_AUTH);
  auth = null;
  $('user-dropdown').hidden = true;
  mostrarLogin();
  if (expirou) $('l-erro').textContent = 'Sessão expirada. Entre novamente.';
}

function toggleMenu(ev) {
  ev.stopPropagation();
  $('user-dropdown').hidden = !$('user-dropdown').hidden;
}

document.addEventListener('click', () => {
  const d = $('user-dropdown');
  if (d) d.hidden = true;
});

async function iniciarApp() {
  $('login-screen').hidden = true;
  $('app').hidden = false;
  $('user-btn').textContent = auth.nome;
  $('user-who').textContent = auth.nome + ' (' + auth.usuario + ')'
    + (auth.admin ? ' · administrador' : '');
  $('menu-admin').hidden = !auth.admin;
  await carregarRegioes();
  carregarTudo();
  carregarFiltrosDemandas();
  mostrarView('emendas');
}

// ============================================================
// NAVEGAÇÃO
// ============================================================
function mostrarView(v) {
  ['emendas', 'demandas', 'painel', 'atividade', 'lixeira'].forEach(n => {
    $('view-' + n).hidden = (n !== v);
  });
  document.querySelectorAll('#nav button').forEach(b => {
    b.classList.toggle('active', b.dataset.view === v);
  });
  if (v === 'demandas') carregarDemandas();
  if (v === 'painel') carregarPainel();
  if (v === 'atividade') carregarLogs(true);
  if (v === 'lixeira') carregarLixeira();
}

// ============================================================
// REGIÕES
// ============================================================
async function carregarRegioes() {
  try {
    const lista = await api('/api/regioes');
    regioesMap = {};
    const regs = new Set();
    lista.forEach(x => { regioesMap[chaveMun(x.m)] = x.r; regs.add(x.r); });
    $('lista-municipios').innerHTML = lista.map(x =>
      '<option>' + escapeHTML(x.m) + '</option>').join('');
    $('lista-regioes').innerHTML = [...regs].sort().map(r =>
      '<option>' + escapeHTML(r) + '</option>').join('');
  } catch (err) { console.error(err); }
}

function configurarAutoRegiao() {
  $('f-regiao').addEventListener('input', () => { regiaoEditadaManualmente = true; });
  $('f-municipio').addEventListener('input', function () {
    if (regiaoEditadaManualmente) return;
    $('f-regiao').value = regioesMap[chaveMun(this.value)] || '';
  });
}

// ============================================================
// LISTAGEM EMENDAS
// ============================================================
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

// ============================================================
// FICHA EMENDA
// ============================================================
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

function campoFicha(rotulo, valor, opts) {
  opts = opts || {};
  const vazio = valor == null || valor === '' || valor === NSC;
  const txt = vazio ? '<span class="faint">' + (opts.vazio || '—') + '</span>' : escapeHTML(valor);
  return '<div class="ficha-field' + (opts.full ? ' full' : '') + '"><label>' + rotulo + '</label><div' + (opts.pre ? ' class="pre"' : '') + '>' + txt + '</div></div>';
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

// ============================================================
// FORMULÁRIO EMENDA
// ============================================================
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

// ============================================================
// DEMANDAS
// ============================================================
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
  btn.disabled = true; btn.textContent = 'Salvando...';
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
    btn.disabled = false; btn.textContent = 'Salvar';
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

// ============================================================
// PAINEL
// ============================================================
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
      '<div><div class="n">' + Math.round(t.mediana) + '</
