// ============================================================
// SISTEMA — importação, usuários, senha, regiões e INIT
// Depende de: core.js, emendas.js, demandas.js, painel.js
// Deve ser o ÚLTIMO script carregado.
// ============================================================

// ---------- IMPORTAÇÃO ----------
function abrirModalImportar() {
  $('imp-arquivo').value = '';
  resetarPreview();
  $('modal-importar').classList.add('open');
}
function fecharModalImportar() { $('modal-importar').classList.remove('open'); }
function resetarPreview() {
  previewOk = false;
  $('btn-importar').disabled = true;
  $('imp-preview').innerHTML = '';
}

function listaMudancas(itens) {
  return itens.map(i =>
    '<div class="it"><b>' + escapeHTML(fmtNumero(i.numero)) + '</b> · ' + escapeHTML(i.municipio) + (i.ano ? ' · ' + i.ano : '') +
    (i.mudancas || []).map(m => '<div style="color:var(--muted);">' + escapeHTML(m.campo) + ': ' + (m.de ? '<span style="text-decoration:line-through;color:var(--faint);">' + escapeHTML(m.de) + '</span> → ' : '') + escapeHTML(m.para || '(vazio)') + '</div>').join('') + '</div>'
  ).join('');
}

function blocoImport(chave, v) {
  if (v.tipo === 'ausente') {
    return '<div class="imp-bloco"><div class="imp-bloco-h">Aba ' + escapeHTML(chave) + '</div><div class="imp-bloco-b">' +
      '<span style="color:var(--muted);">Aba não encontrada na planilha. Será ignorada.</span></div></div>';
  }
  const nc = Object.entries(v.nao_consta || {}).map(([k, n]) => k + ': ' + n).join(' · ');
  const ign = v.lista_ignoradas || [];
  const avisos = v.avisos || [];
  return '<div class="imp-bloco"><div class="imp-bloco-h">Aba ' + escapeHTML(chave) + ' · ' + v.total_linhas + ' linhas válidas</div><div class="imp-bloco-b">' +
    '<span class="tag nova">' + v.novas + ' novas</span><span class="tag alt">' + v.alteradas + ' alteradas</span><span class="tag">' + v.iguais + ' sem alteração</span>' +
    (v.ignoradas ? '<span class="tag">' + v.ignoradas + ' ignoradas</span>' : '') +
    (v.duplicadas ? '<span class="tag">' + v.duplicadas + ' repetidas na planilha</span>' : '') +
    '<div style="margin-top:6px;color:var(--muted);">' + v.pagas + ' pagas · ' + v.aguardando + ' aguardando' + (v.sem_numero ? ' · ' + v.sem_numero + ' sem nº na planilha' : '') + '</div>' +
    (nc ? '<div class="hint" style="margin-top:4px;">Campos sem informação ("não consta na planilha"): ' + escapeHTML(nc) + '</div>' : '') +
    (v.exemplos_novas.length ? '<details><summary>Ver exemplos de emendas novas</summary><div class="imp-lista">' + v.exemplos_novas.map(n => '<div class="it"><b>' + escapeHTML(fmtNumero(n.numero)) + '</b> · ' + escapeHTML(n.municipio) + ' · ' + fmtMoney(n.valor) + '</div>').join('') + '</div></details>' : '') +
    (v.lista_alteradas.length ? '<details><summary>Ver alterações (' + v.alteradas + (v.alteradas > v.lista_alteradas.length ? ', mostrando ' + v.lista_alteradas.length : '') + ')</summary><div class="imp-lista">' + listaMudancas(v.lista_alteradas) + '</div></details>' : '') +
    (v.ignoradas ? '<details><summary>Ver linhas ignoradas (' + v.ignoradas + ')</summary><div class="imp-lista">' +
      ign.map(i => '<div class="it">Linha ' + i.linha + ' · ' + escapeHTML(i.motivo) + '</div>').join('') +
      (v.ignoradas > ign.length ? '<div class="it faint">… e mais ' + (v.ignoradas - ign.length) + '</div>' : '') + '</div></details>' : '') +
    (avisos.length ? '<details><summary style="color:var(--warn);">Ver avisos (' + (v.n_avisos || avisos.length) + ')</summary><div class="imp-lista">' +
      avisos.map(a => '<div class="it">' + escapeHTML(a) + '</div>').join('') +
      ((v.n_avisos || 0) > avisos.length ? '<div class="it faint">… e mais ' + (v.n_avisos - avisos.length) + '</div>' : '') + '</div></details>' : '') +
    '</div></div>';
}

async function chamarImportacao(rota) {
  const arquivo = $('imp-arquivo').files[0];
  if (!arquivo) { toast('Selecione um arquivo', 'error'); return null; }
  const fd = new FormData();
  fd.append('arquivo', arquivo);
  fd.append('aba', $('imp-aba').value);
  return api(rota, { method: 'POST', body: fd });
}

async function previewImportar() {
  const box = $('imp-preview');
  resetarPreview();
  if (!$('imp-arquivo').files[0]) { toast('Selecione um arquivo', 'error'); return; }
  box.innerHTML = '<span class="hint">Lendo planilha…</span>';
  $('btn-preview').disabled = true;
  try {
    const data = await chamarImportacao('/api/importar/preview');
    const abas = data.abas, chaves = Object.keys(abas);
    box.innerHTML = chaves.map(k => blocoImport(k, abas[k])).join('');
    const mudancas = chaves.reduce((s, k) => s + (abas[k].novas || 0) + (abas[k].alteradas || 0), 0);
    previewOk = mudancas > 0;
    $('btn-importar').disabled = !previewOk;
    if (!mudancas) box.insertAdjacentHTML('afterbegin', '<div class="hint" style="margin-top:8px;">Nenhuma diferença em relação ao que já está no sistema.</div>');
  } catch (err) {
    box.innerHTML = '<span style="color:var(--bad);">' + escapeHTML(err.message) + '</span>';
  } finally {
    $('btn-preview').disabled = false;
  }
}

async function executarImportar() {
  if (!previewOk) { toast('Faça a pré-visualização antes de importar', 'error'); return; }
  if (!confirm('Aplicar as alterações mostradas na pré-visualização?')) return;
  const btn = $('btn-importar');
  btn.disabled = true;
  btn.textContent = 'Importando…';
  try {
    const data = await chamarImportacao('/api/importar');
    toast(data.criadas + ' novas, ' + data.atualizadas + ' atualizadas, ' + data.sem_alteracao + ' sem alteração');
    fecharModalImportar();
    carregarTudo();
    carregarRegioes();
  } catch (err) {
    toast('Falha: ' + err.message, 'error');
  } finally {
    btn.textContent = 'Importar';
    btn.disabled = !previewOk;
  }
}

// ---------- SENHA ----------
function mostrarSenhas(ids, ligado) {
  ids.forEach(i => { $(i).type = ligado ? 'text' : 'password'; });
}

// obrigatoria === true: troca exigida pelo sistema (não pode ser fechada)
function abrirSenha(obrigatoria) {
  senhaObrigatoria = obrigatoria === true;
  ['s-atual', 's-nova', 's-nova2'].forEach(i => { $(i).value = ''; $(i).type = 'password'; });
  $('senha-mostrar').checked = false;
  $('senha-erro').textContent = '';
  $('senha-aviso').hidden = !senhaObrigatoria;
  $('senha-fechar').hidden = senhaObrigatoria;
  $('senha-cancelar').hidden = senhaObrigatoria;
  $('senha-titulo').textContent = senhaObrigatoria ? 'Defina uma nova senha' : 'Alterar senha';
  $('modal-senha').classList.add('open');
  setTimeout(() => $('s-atual').focus(), 100);
}

function fecharSenha() {
  if (senhaObrigatoria) return;
  $('modal-senha').classList.remove('open');
}

async function salvarSenha() {
  const atual = $('s-atual').value, nova = $('s-nova').value, nova2 = $('s-nova2').value;
  const erro = $('senha-erro');
  erro.textContent = '';
  if (!atual || !nova) { erro.textContent = 'Preencha a senha atual e a nova senha.'; return; }
  if (nova !== nova2) { erro.textContent = 'As senhas novas não conferem.'; return; }
  if (nova.length < 8 || !/[A-Za-z]/.test(nova) || !/\d/.test(nova)) {
    erro.textContent = 'A nova senha precisa ter ao menos 8 caracteres, com letras e números.';
    return;
  }
  const btn = $('senha-salvar');
  btn.disabled = true;
  try {
    await api('/api/senha', { method: 'PUT', json: { atual, nova } });
    const eraObrigatoria = senhaObrigatoria;
    senhaObrigatoria = false;
    $('modal-senha').classList.remove('open');
    toast('Senha alterada');
    if (eraObrigatoria) {
      auth.deve_trocar_senha = false;
      localStorage.setItem(CHAVE_AUTH, JSON.stringify(auth));
      iniciarApp();
    }
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function encerrarOutrasSessoes() {
  if (!confirm('Desconectar este usuário de todos os outros navegadores e dispositivos?')) return;
  try {
    const r = await api('/api/sessoes/outras', { method: 'DELETE' });
    toast(r.encerradas ? r.encerradas + ' sessão(ões) encerrada(s)' : 'Não há outras sessões abertas');
  } catch (err) { toast(err.message, 'error'); }
}

// ---------- USUÁRIOS ----------
let usuariosCache = [];

async function abrirUsuarios() {
  $('modal-usuarios').classList.add('open');
  resetarFormUsuario();
  await carregarUsuarios();
}
function fecharUsuarios() { $('modal-usuarios').classList.remove('open'); }

function _pill(txt, cls) {
  return '<span class="pill pill-' + cls + '">' + txt + '</span>';
}

async function carregarUsuarios() {
  try {
    usuariosCache = await api('/api/usuarios');
    $('tbody-usuarios').innerHTML = usuariosCache.map(u => {
      const eu = auth && u.id === auth.id;
      const sit = !u.ativo ? _pill('Desativado', 'bad')
        : u.bloqueado ? _pill('Bloqueado', 'warn')
        : u.deve_trocar_senha ? _pill('Troca de senha pendente', 'neutral')
        : _pill('Ativo', 'ok');
      const botoes =
        '<button class="btn btn-secondary btn-sm" onclick="editarUsuario(' + u.id + ')">Editar</button>' +
        '<button class="btn btn-secondary btn-sm" onclick="abrirRedef(' + u.id + ')">Senha</button>' +
        (u.bloqueado ? '<button class="btn btn-secondary btn-sm" onclick="desbloquearUsuario(' + u.id + ')">Desbloquear</button>' : '') +
        (!eu ? '<button class="btn btn-secondary btn-sm" onclick="alternarAtivoUsuario(' + u.id + ')">' + (u.ativo ? 'Desativar' : 'Ativar') + '</button>' : '') +
        (!eu ? '<button class="btn btn-danger btn-sm" onclick="removerUsuario(' + u.id + ')">Remover</button>' : '');
      return '<tr style="cursor:default;">' +
        '<td>' + escapeHTML(u.nome) + (eu ? ' ' + _pill('você', 'neutral') : '') + '</td>' +
        '<td>' + escapeHTML(u.usuario) + '</td>' +
        '<td>' + (u.admin ? 'Administrador' : 'Usuário') + '</td>' +
        '<td>' + sit + '</td>' +
        '<td>' + (u.ultimo_login ? escapeHTML(fmtDataHora(u.ultimo_login)) : '<span class="faint">nunca</span>') + '</td>' +
        '<td class="right"><div class="acoes-usuario">' + botoes + '</div></td></tr>';
    }).join('');
  } catch (err) { toast(err.message, 'error'); }
}

function resetarFormUsuario() {
  ['u-id', 'u-nome', 'u-usuario', 'u-senha'].forEach(i => { $(i).value = ''; });
  $('u-usuario').disabled = false;
  $('u-admin').checked = false;
  $('u-admin').disabled = false;
  $('u-grupo-senha').hidden = false;
  $('u-erro').textContent = '';
  $('u-form-titulo').textContent = 'Novo usuário';
  $('u-salvar').textContent = 'Adicionar usuário';
  $('u-cancelar').hidden = true;
}

function editarUsuario(id) {
  const u = usuariosCache.find(x => x.id === id);
  if (!u) return;
  resetarFormUsuario();
  $('u-id').value = u.id;
  $('u-nome').value = u.nome;
  $('u-usuario').value = u.usuario;
  $('u-usuario').disabled = true;
  $('u-admin').checked = !!u.admin;
  // o próprio perfil não pode ser alterado (evita ficar sem administrador)
  $('u-admin').disabled = !!(auth && u.id === auth.id);
  $('u-grupo-senha').hidden = true;
  $('u-form-titulo').textContent = 'Editar usuário: ' + u.usuario;
  $('u-salvar').textContent = 'Salvar alterações';
  $('u-cancelar').hidden = false;
  $('u-nome').focus();
}

async function salvarUsuario() {
  const erro = $('u-erro');
  erro.textContent = '';
  const id = $('u-id').value;
  const nome = $('u-nome').value.trim();
  if (nome.length < 2) { erro.textContent = 'Informe o nome do usuário.'; return; }

  let rota, metodo, corpo;
  if (id) {
    rota = '/api/usuarios/' + id; metodo = 'PUT';
    corpo = { nome, admin: $('u-admin').checked };
  } else {
    const login = $('u-usuario').value.trim().toLowerCase();
    const senha = $('u-senha').value;
    if (!/^[a-z0-9._-]{3,30}$/.test(login)) {
      erro.textContent = 'Login inválido: 3 a 30 caracteres entre letras, números, ponto, hífen e sublinhado.';
      return;
    }
    if (senha.length < 8 || !/[A-Za-z]/.test(senha) || !/\d/.test(senha)) {
      erro.textContent = 'A senha precisa ter ao menos 8 caracteres, com letras e números.';
      return;
    }
    rota = '/api/usuarios'; metodo = 'POST';
    corpo = { nome, usuario: login, senha, admin: $('u-admin').checked };
  }
  const btn = $('u-salvar');
  btn.disabled = true;
  try {
    await api(rota, { method: metodo, json: corpo });
    toast(id ? 'Usuário atualizado' : 'Usuário criado. Ele deverá trocar a senha no primeiro acesso.');
    resetarFormUsuario();
    await carregarUsuarios();
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function alternarAtivoUsuario(id) {
  const u = usuariosCache.find(x => x.id === id);
  if (!u) return;
  const msg = u.ativo
    ? 'Desativar ' + u.usuario + '? Ele será desconectado e não poderá entrar até ser reativado.'
    : 'Reativar ' + u.usuario + '?';
  if (!confirm(msg)) return;
  try {
    await api('/api/usuarios/' + id, { method: 'PUT', json: { ativo: !u.ativo } });
    toast(u.ativo ? 'Usuário desativado' : 'Usuário reativado');
    carregarUsuarios();
  } catch (err) { toast(err.message, 'error'); }
}

async function desbloquearUsuario(id) {
  try {
    await api('/api/usuarios/' + id + '/desbloquear', { method: 'POST' });
    toast('Usuário desbloqueado');
    carregarUsuarios();
  } catch (err) { toast(err.message, 'error'); }
}

async function removerUsuario(id) {
  const u = usuariosCache.find(x => x.id === id);
  if (!u) return;
  if (!confirm('Remover ' + u.usuario + ' definitivamente? Para apenas bloquear o acesso, use "Desativar".')) return;
  try {
    await api('/api/usuarios/' + id, { method: 'DELETE' });
    toast('Usuário removido');
    carregarUsuarios();
  } catch (err) { toast(err.message, 'error'); }
}

function abrirRedef(id) {
  const u = usuariosCache.find(x => x.id === id);
  if (!u) return;
  $('redef-id').value = id;
  $('redef-senha').value = '';
  $('redef-senha').type = 'password';
  $('redef-erro').textContent = '';
  $('redef-quem').textContent = 'Usuário: ' + u.nome + ' (' + u.usuario + ')';
  $('modal-redef').classList.add('open');
  setTimeout(() => $('redef-senha').focus(), 100);
}
function fecharRedef() { $('modal-redef').classList.remove('open'); }

async function salvarRedefinicao() {
  const id = $('redef-id').value, nova = $('redef-senha').value;
  const erro = $('redef-erro');
  erro.textContent = '';
  if (nova.length < 8 || !/[A-Za-z]/.test(nova) || !/\d/.test(nova)) {
    erro.textContent = 'A senha precisa ter ao menos 8 caracteres, com letras e números.';
    return;
  }
  try {
    await api('/api/usuarios/' + id + '/senha', { method: 'PUT', json: { nova } });
    toast('Senha redefinida. O usuário deverá trocá-la no próximo acesso.');
    fecharRedef();
    carregarUsuarios();
  } catch (err) { erro.textContent = err.message; }
}

// ---------- REGIÕES (importação) ----------
function abrirRegioes() {
  $('reg-arquivo').value = '';
  $('reg-info').textContent = Object.keys(regioesMap).length + ' municípios cadastrados atualmente.';
  $('modal-regioes').classList.add('open');
}
function fecharRegioes() { $('modal-regioes').classList.remove('open'); }

async function enviarRegioes() {
  const arq = $('reg-arquivo').files[0];
  if (!arq) { toast('Selecione um arquivo', 'error'); return; }
  const fd = new FormData();
  fd.append('arquivo', arq);
  try {
    const r = await api('/api/regioes/importar', { method: 'POST', body: fd });
    toast(r.municipios + ' municípios importados; ' + r.emendas_atualizadas + ' emendas atualizadas');
    await carregarRegioes();
    carregarTudo();
    fecharRegioes();
  } catch (err) { toast(err.message, 'error'); }
}

// ============================================================
// INIT
// ============================================================
document.addEventListener('DOMContentLoaded', function () {
  document.title = NOME_SISTEMA;
  document.querySelectorAll('[data-nome-sistema]').forEach(el => { el.textContent = NOME_SISTEMA; });
  configurarAutoRegiao();

  document.querySelectorAll('thead th.sortable').forEach(th =>
    th.addEventListener('click', () => {
      if (th.dataset.scope === 'dem') return;
      sortBy(th.dataset.sort);
    }));
  document.querySelectorAll('th[data-scope="dem"].sortable').forEach(th =>
    th.addEventListener('click', () => sortByDem(th.dataset.sort)));

  document.querySelectorAll('#nav button').forEach(b =>
    b.addEventListener('click', () => mostrarView(b.dataset.view)));

  setupOverlayClose($('modal-overlay'), fecharModal);
  setupOverlayClose($('modal-ficha'), fecharFicha);
  setupOverlayClose($('modal-demanda'), fecharModalDemanda);
  setupOverlayClose($('modal-ficha-demanda'), fecharFichaDemanda);
  setupOverlayClose($('modal-importar'), fecharModalImportar);
  setupOverlayClose($('modal-usuarios'), fecharUsuarios);
  setupOverlayClose($('modal-redef'), fecharRedef);
  setupOverlayClose($('modal-senha'), fecharSenha);
  setupOverlayClose($('modal-regioes'), fecharRegioes);

  $('form-emenda').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault();
  });
  $('form-demanda').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault();
  });
  ['s-atual', 's-nova', 's-nova2'].forEach(i =>
    $(i).addEventListener('keydown', e => { if (e.key === 'Enter') salvarSenha(); }));
  $('redef-senha').addEventListener('keydown', e => { if (e.key === 'Enter') salvarRedefinicao(); });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      fecharModal(); fecharFicha();
      fecharModalDemanda(); fecharFichaDemanda();
      fecharModalImportar();
      fecharRedef(); fecharUsuarios(); fecharSenha(); fecharRegioes();
    }
  });

  try { auth = JSON.parse(localStorage.getItem(CHAVE_AUTH) || 'null'); }
  catch (e) { auth = null; }
  if (auth && auth.token) iniciarApp(); else mostrarLogin();
});
