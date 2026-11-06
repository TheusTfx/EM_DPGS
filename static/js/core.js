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
// Emendas começam ordenadas pelo ano da emenda (coluna "Emenda"), crescente
let sortColumn = 'ano', sortDirection = 'asc';
let sortColumnDem = null, sortDirectionDem = 'desc';
let fichaAtualId = null;
let fichaAtualDemandaId = null;
let regiaoEditadaManualmente = false;
let regioesMap = {};
let previewOk = false;
let logsOffset = 0;
let painelDados = null;
let senhaObrigatoria = false;
const painelModo = { lider: 'n', municipio: 'n', regiao: 'n', secretaria: 'n' };

// ---------- Utilitários ----------
const $ = id => document.getElementById(id);

// Versões tolerantes: não quebram se o elemento não existir no HTML
function _hidden(id, valor) {
  const el = $(id);
  if (el) el.hidden = valor;
  else console.warn('Elemento não encontrado no HTML: #' + id);
}
function _checked(id, valor) {
  const el = $(id);
  if (el) el.checked = valor;
}
function _modoDemandas() {
  const el = $('mostrar-demandas');
  return !!(el && el.checked);
}

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

// Comparação genérica usada na ordenação de emendas e demandas.
// Valores vazios ficam sempre no fim, em qualquer direção.
function _comparar(va, vb, dir) {
  if (va == null && vb == null) return 0;
  if (va == null) return 1;
  if (vb == null) return -1;
  if (typeof va === 'number' && typeof vb === 'number') {
    return dir === 'desc' ? vb - va : va - vb;
  }
  const sa = String(va).trim(), sb = String(vb).trim();
  if (/^\d+(\.\d+)?$/.test(sa) && /^\d+(\.\d+)?$/.test(sb)) {
    return dir === 'desc' ? parseFloat(sb) - parseFloat(sa) : parseFloat(sa) - parseFloat(sb);
  }
  return dir === 'desc'
    ? sb.toLowerCase().localeCompare(sa.toLowerCase(), 'pt-BR')
    : sa.toLowerCase().localeCompare(sb.toLowerCase(), 'pt-BR');
}

// Slug usado nas classes CSS de situação/status (ex.: "Enviado ao Estado" -> "enviado-ao-estado")
function _slugSituacao(s) {
  return String(s || 'Aguardando').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
}
function badgeSituacao(s) {
  return '<span class="status status-' + _slugSituacao(s) + '">' + escapeHTML(s || 'Aguardando') + '</span>';
}
function badgeStatusDemanda(s) {
  return '<span class="status status-' + _slugSituacao(s) + '">' + escapeHTML(s || 'Aguardando') + '</span>';
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
  if (res.status === 403 && data && data.trocar_senha) {
    if (auth) auth.deve_trocar_senha = true;
    if (!senhaObrigatoria) abrirSenha(true);
    throw new Error(data.erro);
  }
  if (!res.ok) {
    let msg = data && data.erro;
    if (!msg) {
      msg = res.status >= 500
        ? 'O servidor não respondeu (erro ' + res.status + '). Tente novamente em instantes.'
        : 'Erro ' + res.status;
    }
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// ---------- Auth ----------
function toggleOlho(id, btn) {
  const el = $(id);
  const mostrar = el.type === 'password';
  el.type = mostrar ? 'text' : 'password';
  btn.textContent = mostrar ? 'Ocultar' : 'Mostrar';
  btn.setAttribute('aria-label', mostrar ? 'Ocultar senha' : 'Mostrar senha');
}

function mostrarLogin() {
  $('app').hidden = true;
  $('login-screen').hidden = false;
  $('l-senha').value = '';
  $('l-senha').type = 'password';
  const olho = document.querySelector('#login-screen .btn-olho');
  if (olho) { olho.textContent = 'Mostrar'; olho.setAttribute('aria-label', 'Mostrar senha'); }
  setTimeout(() => $('l-usuario').focus(), 50);
}

async function entrar(ev) {
  ev.preventDefault();
  const btn = $('l-btn');
  if (btn.disabled) return;
  const usuario = $('l-usuario').value.trim();
  const senha = $('l-senha').value;
  $('l-erro').textContent = '';
  $('l-info').textContent = '';
  if (!usuario || !senha) {
    $('l-erro').textContent = 'Informe usuário e senha.';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Entrando…';
  // servidor gratuito do Render pode levar alguns segundos para acordar
  const aviso = setTimeout(() => {
    $('l-info').textContent = 'O servidor pode estar iniciando. Aguarde alguns segundos…';
  }, 4000);
  let ok = false;
  try {
    const d = await api('/api/login', { method: 'POST', json: { usuario, senha } });
    auth = d;
    localStorage.setItem(CHAVE_AUTH, JSON.stringify(d));
    ok = true;
  } catch (err) {
    $('l-erro').textContent = err.status
      ? err.message
      : 'Não foi possível conectar ao servidor. Verifique a internet e tente novamente.';
    $('l-senha').value = '';
    $('l-senha').focus();
  } finally {
    clearTimeout(aviso);
    $('l-info').textContent = '';
    btn.disabled = false;
    btn.textContent = 'Entrar';
  }
  if (ok) iniciarApp();
}

function sair(expirou) {
  if (!expirou && auth && auth.token) {
    // encerra a sessão no servidor (sem esperar resposta)
    fetch('/api/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + auth.token } })
      .catch(() => {});
  }
  localStorage.removeItem(CHAVE_AUTH);
  auth = null;
  senhaObrigatoria = false;
  // limpa dados em memória e volta ao modo emendas
  emendasCache = [];
  demandasCache = [];
  painelDados = null;
  _checked('mostrar-demandas', false);
  _checked('mostrar-demandas-dem', false);
  ['modal-senha', 'modal-usuarios', 'modal-redef'].forEach(id => {
    const m = $(id);
    if (m) m.classList.remove('open');
  });
  $('user-dropdown').hidden = true;
  mostrarLogin();
  $('l-erro').textContent = expirou ? 'Sessão expirada. Entre novamente.' : '';
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
  // confirma a sessão no servidor e atualiza perfil / exigência de troca de senha
  try {
    const me = await api('/api/me');
    auth = Object.assign({}, auth, me);
    localStorage.setItem(CHAVE_AUTH, JSON.stringify(auth));
  } catch (err) {
    if (auth) {
      mostrarLogin();
      $('l-erro').textContent = err.status
        ? err.message
        : 'Não foi possível conectar ao servidor. Tente novamente.';
    }
    return;
  }

  $('login-screen').hidden = true;
  $('app').hidden = false;
  $('user-btn').textContent = auth.nome;
  $('user-who').textContent = auth.nome + ' (' + auth.usuario + ')'
    + (auth.admin ? ' · administrador' : '');
  $('menu-admin').hidden = !auth.admin;

  if (auth.deve_trocar_senha) {
    abrirSenha(true);
    return;
  }
  await carregarRegioes();
  // mostrarView já carrega emendas/demandas e seus filtros
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
    const modoDemandas = _modoDemandas();

    // Primeiro dispara o carregamento dos dados, para que nada
    // no ajuste visual abaixo possa impedir a lista de aparecer.
    if (modoDemandas) {
      carregarDemandas();
      carregarFiltrosDemandas();
    } else {
      carregarEmendas();
      carregarFiltros();
    }

    _checked('mostrar-demandas-dem', modoDemandas);
    _hidden('kpis-emendas', modoDemandas);
    _hidden('kpis-demandas', !modoDemandas);
    _hidden('toolbar-emendas', modoDemandas);
    _hidden('toolbar-demandas', !modoDemandas);
    _hidden('tabela-emendas', modoDemandas);
    _hidden('tabela-demandas-card', !modoDemandas);

    // subtítulo é opcional: só atualiza se existir no HTML
    const sub = $('subtitulo-modo');
    if (sub) {
      sub.textContent = modoDemandas
        ? 'demandas extras'
        : 'controle de emendas parlamentares';
    }

    const btnNovo = $('btn-novo');
    const btnImp = $('btn-importar-emendas');
    if (btnNovo) {
      btnNovo.textContent = modoDemandas ? 'Nova demanda' : 'Nova emenda';
      btnNovo.onclick = modoDemandas
        ? function () { abrirModalDemanda(); }
        : function () { abrirModal(); };
    }
    if (btnImp) btnImp.hidden = modoDemandas;
  }
}

// valor === false  -> desliga (usado pelo checkbox dentro dos filtros de demandas)
// valor indefinido -> segue o checkbox dos filtros de emendas
function alternarDemandas(valor) {
  const ligado = (valor === false) ? false : _modoDemandas();
  _checked('mostrar-demandas', ligado);
  _checked('mostrar-demandas-dem', ligado);
  mostrarView('emendas');
  // abre o painel de filtros das demandas para o usuário ver onde desligar
  if (ligado) _hidden('filtros-painel-demandas', false);
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
