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
  if (v.tipo === 'contatos') {
    return '<div class="imp-bloco"><div class="imp-bloco-h">Contatos (aba ENTIDADES)</div><div class="imp-bloco-b">' +
      '<b>' + v.encontradas + '</b> entidades localizadas · <b>' + v.alteradas + '</b> emendas com contatos novos ou alterados' +
      (v.n_nao_encontradas ? ' · <span style="color:var(--warn);">' + v.n_nao_encontradas + ' sem correspondência</span>' : '') +
      (v.lista_alteradas.length ? '<details><summary>Ver alterações</summary><div class="imp-lista">' + listaMudancas(v.lista_alteradas) + '</div></details>' : '') +
      (v.nao_encontradas.length ? '<details><summary>Ver entidades sem correspondência</summary><div class="imp-lista">' + v.nao_encontradas.map(n => '<div class="it">' + escapeHTML(n) + '</div>').join('') + '</div></details>' : '') + '</div></div>';
  }
  const nc = Object.entries(v.nao_consta || {}).map(([k, n]) => k + ': ' + n).join(' · ');
  return '<div class="imp-bloco"><div class="imp-bloco-h">Aba ' + chave + ' · ' + v.total_linhas + ' linhas</div><div class="imp-bloco-b">' +
    '<span class="tag nova">' + v.novas + ' novas</span><span class="tag alt">' + v.alteradas + ' alteradas</span><span class="tag">' + v.iguais + ' sem alteração</span>' +
    (v.ignoradas ? '<span class="tag">' + v.ignoradas + ' ignoradas</span>' : '') +
    '<div style="margin-top:6px;color:var(--muted);">' + v.pagas + ' pagas · ' + v.aguardando + ' aguardando' + (v.sem_numero ? ' · ' + v.sem_numero + ' sem nº na planilha' : '') + '</div>' +
    (nc ? '<div class="hint" style="margin-top:4px;">Campos sem informação ("não consta na planilha"): ' + escapeHTML(nc) + '</div>' : '') +
    (v.exemplos_novas.length ? '<details><summary>Ver exemplos de emendas novas</summary><div class="imp-lista">' + v.exemplos_novas.map(n => '<div class="it"><b>' + escapeHTML(fmtNumero(n.numero)) + '</b> · ' + escapeHTML(n.municipio) + ' · ' + fmtMoney(n.valor) + '</div>').join('') + '</div></details>' : '') +
    (v.lista_alteradas.length ? '<details><summary>Ver alterações (' + v.alteradas + (v.alteradas > v.lista_alteradas.length ? ', mostrando ' + v.lista_alteradas.length : '') + ')</summary><div class="imp-lista">' + listaMudancas(v.lista_alteradas) + '</div></details>' : '') +
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
    previewOk = true;
    $('btn-importar').disabled = false;
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
    toast(data.importadas + ' emendas novas ou atualizadas');
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

// ---------- USUÁRIOS ----------
function abrirSenha() {
  ['s-atual', 's-nova', 's-nova2'].forEach(i => { $(i).value = ''; });
  $('modal-senha').classList.add('open');
}
function fecharSenha() { $('modal-senha').classList.remove('open'); }
async function salvarSenha() {
  if ($('s-nova').value !== $('s-nova2').value) {
    toast('As senhas novas não conferem', 'error');
    return;
  }
  try {
    await api('/api/senha', {
      method: 'PUT',
      json: { atual: $('s-atual').value, nova: $('s-nova').value }
    });
    toast('Senha alterada');
    fecharSenha();
  } catch (err) { toast(err.message, 'error'); }
}

async function abrirUsuarios() {
  $('modal-usuarios').classList.add('open');
  ['u-nome', 'u-usuario', 'u-senha'].forEach(i => { $(i).value = ''; });
  $('u-admin').checked = false;
  await carregarUsuarios();
}
function fecharUsuarios() { $('modal-usuarios').classList.remove('open'); }

async function carregarUsuarios() {
  try {
    const lista = await api('/api/usuarios');
    $('tbody-usuarios').innerHTML = lista.map(u =>
      '<tr style="cursor:default;"><td>' + escapeHTML(u.nome) + '</td><td>' + escapeHTML(u.usuario) + '</td><td>' + (u.admin ? 'Administrador' : 'Usuário') + '</td>' +
      '<td class="right" style="white-space:nowrap;"><button class="btn btn-secondary btn-sm" onclick="redefinirSenha(' + u.id + ')">Redefinir senha</button>' +
      (u.id !== auth.id && u.usuario !== auth.usuario ? ' <button class="btn btn-danger btn-sm" onclick="removerUsuario(' + u.id + ')">Remover</button>' : '') + '</td></tr>'
    ).join('');
  } catch (err) { toast(err.message, 'error'); }
}

async function criarUsuario() {
  try {
    await api('/api/usuarios', {
      method: 'POST',
      json: {
        nome: $('u-nome').value,
        usuario: $('u-usuario').value,
        senha: $('u-senha').value,
        admin: $('u-admin').checked
      }
    });
    toast('Usuário criado');
    ['u-nome', 'u-usuario', 'u-senha'].forEach(i => { $(i).value = ''; });
    $('u-admin').checked = false;
    carregarUsuarios();
  } catch (err) { toast(err.message, 'error'); }
}

async function redefinirSenha(id) {
  const nova = prompt('Nova senha para este usuário (mínimo 6 caracteres):');
  if (!nova) return;
  try {
    await api('/api/usuarios/' + id + '/senha', { method: 'PUT', json: { nova } });
    toast('Senha redefinida');
  } catch (err) { toast(err.message, 'error'); }
}

async function removerUsuario(id) {
  if (!confirm('Remover este usuário?')) return;
  try {
    await api('/api/usuarios/' + id, { method: 'DELETE' });
    toast('Usuário removido');
    carregarUsuarios();
  } catch (err) { toast(err.message, 'error'); }
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
  document.querySelectorAll('#chips-dias .chip').forEach(c =>
    c.addEventListener('click', () => {
      $('filtro-parada').value = ($('filtro-parada').value === c.dataset.d) ? '' : c.dataset.d;
      marcarChips();
      carregarEmendas();
    }));

  setupOverlayClose($('modal-overlay'), fecharModal);
  setupOverlayClose($('modal-ficha'), fecharFicha);
  setupOverlayClose($('modal-demanda'), fecharModalDemanda);
  setupOverlayClose($('modal-ficha-demanda'), fecharFichaDemanda);
  setupOverlayClose($('modal-importar'), fecharModalImportar);
  setupOverlayClose($('modal-usuarios'), fecharUsuarios);
  setupOverlayClose($('modal-senha'), fecharSenha);
  setupOverlayClose($('modal-regioes'), fecharRegioes);

  $('form-emenda').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault();
  });
  $('form-demanda').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      fecharModal(); fecharFicha();
      fecharModalDemanda(); fecharFichaDemanda();
      fecharModalImportar();
      fecharUsuarios(); fecharSenha(); fecharRegioes();
    }
  });

  try { auth = JSON.parse(localStorage.getItem(CHAVE_AUTH) || 'null'); }
  catch (e) { auth = null; }
  if (auth && auth.token) iniciarApp(); else mostrarLogin();
});
