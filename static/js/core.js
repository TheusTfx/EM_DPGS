// ============================================================
// CORE — constantes, estado global, utilitários, API, auth, nav
// Deve ser carregado PRIMEIRO.
// ============================================================

const NOME_SISTEMA = 'Controle de Emendas';
const NSC = 'não consta na planilha';
const CHAVE_AUTH = 'emendas_auth';

// Estado global (compartilhado entre todos os arquivos)
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

// ---------- Utilitários ----------
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

// ---------- Ícones ----------
function icone(path) {
  return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
}
const ICO_EDIT = '<path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>';
const ICO_DEL = '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>';

// ---------- Toast ----------
function toast(msg, tipo) {
  const el = $('toast');
  $('toast-msg').textContent = msg;
  el.className = 'toast show toast-' + (tipo || 'success');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3800);
}

// ---------- API ----------
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

// ---------- Auth ----------
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

// ---------- Navegação ----------
function mostrarView(v) {
  ['emendas', 'painel', 'atividade', 'lixeira'].forEach(n => {
    $('view-' + n).hidden = (n !== v);
  });
  document.querySelectorAll('#nav button').forEach(b => {
    b.classList.toggle('active', b.dataset.view === v);
  });

  if (v === 'painel') carregarPainel();
  if (v === 'atividade') carregarLogs(true);
  if (v === 'lixeira') carregarLixeira();
  if (v === 'emendas') {
    const modoDemandas = $('mostrar-demandas').checked;

    $('kpis-emendas').hidden = modoDemandas;
    $('kpis-demandas').hidden = !modoDemandas;
    $('toolbar-emendas').hidden = modoDemandas;
    $('toolbar-demandas').hidden = !modoDemandas;
    $('tabela-emendas').hidden = modoDemandas;
    $('tabela-demandas-card').hidden = !modoDemandas;
    $('subtitulo-modo').textContent = modoDemandas
      ? 'demandas extras'
      : 'controle de emendas parlamentares';

    const btnNovo = $('btn-novo');
    const btnImp = $('btn-importar-emendas');
    if (modoDemandas) {
      btnNovo.textContent = 'Nova demanda';
      btnNovo.onclick = abrirModalDemanda;
      if (btnImp) btnImp.hidden = true;
      carregarDemandas();
      carregarFiltrosDemandas();
    } else {
      btnNovo.textContent = 'Nova emenda';
      btnNovo.onclick = abrirModal;
      if (btnImp) btnImp.hidden = false;
      carregarEmendas();
      carregarFiltros();
    }
  }
}

function alternarDemandas() {
  mostrarView('emendas');
}

function toggleFiltros(qual) {
  const el = $('filtros-painel-' + qual);
  if (el) el.hidden = !el.hidden;
}

function _temFiltroAtivo(prefixo) {
  if (prefixo === 'emendas') {
    const ids = ['filtro-situacao','filtro-ano','filtro-municipio',
                 'filtro-secretaria','filtro-lider','filtro-regiao'];
    if ($('filtro-incompletos') && $('filtro-incompletos').checked) return true;
    return ids.some(id => $(id) && $(id).value);
  }
  const ids = ['filtro-status-dem','filtro-ano-dem',
               'filtro-secretaria-dem','filtro-municipio-dem'];
  return ids.some(id => $(id) && $(id).value);
}

// ---------- Regiões ----------
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

// ---------- Helpers de UI ----------
function campoFicha(rotulo, valor, opts) {
  opts = opts || {};
  const vazio = valor == null || valor === '' || valor === NSC;
  const txt = vazio ? '<span class="faint">' + (opts.vazio || '—') + '</span>' : escapeHTML(valor);
  return '<div class="ficha-field' + (opts.full ? ' full' : '') + '"><label>' + rotulo + '</label><div' + (opts.pre ? ' class="pre"' : '') + '>' + txt + '</div></div>';
}

function setupOverlayClose(overlayEl, closeFn) {
  let downOnOverlay = false;
  const setDown = e => { downOnOverlay = (e.target === overlayEl); };
  overlayEl.addEventListener('mousedown', setDown);
  overlayEl.addEventListener('touchstart', setDown, { passive: true });
  overlayEl.addEventListener('click', e => {
    if (downOnOverlay && e.target === overlayEl) closeFn();
    downOnOverlay = false;
  });
}
