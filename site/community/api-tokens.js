(function () {
  'use strict';
  window.renderAPITokens = async function (app, worlds) {
    var C = window.Community, e = C.esc;
    function t(key) { return '<span data-i18n="api_tokens.' + key + '">' + e(window.__('api_tokens.' + key)) + '</span>'; }
    var section = document.createElement('section');
    section.className = 'thread api-tokens';
    section.innerHTML = '<h2>' + t('title') + '</h2><div id="tokenList" aria-live="polite"></div>' +
      '<form id="tokenForm" class="form"><label for="tokenName">' + t('name') + '</label>' +
      '<input id="tokenName" name="name" maxlength="80" required>' +
      '<label for="tokenWorld">' + t('world') + '</label><select id="tokenWorld" name="world_id" required>' +
      '<option value="">' + t('select_world') + '</option>' + worlds.map(function (world) {
        return '<option value="' + e(world.id) + '">' + e(world.name) + '</option>';
      }).join('') + '</select><fieldset><legend>' + t('scope') + '</legend>' +
      '<label><input type="checkbox" name="scopes" value="parallel:read" checked> ' + t('read') + '</label>' +
      '<label><input type="checkbox" name="scopes" value="parallel:run"> ' + t('run') + '</label></fieldset>' +
      '<label for="tokenDays">' + t('days') + '</label><input id="tokenDays" name="expires_days" type="number" min="1" max="365" value="30" required>' +
      '<label for="tokenPassword">' + t('password') + '</label><input id="tokenPassword" name="password" type="password" autocomplete="current-password" required>' +
      '<button class="button" type="submit"' + (worlds.length ? '' : ' disabled') + '>' + t('create') + '</button></form>' +
      '<div id="tokenSecretPanel" hidden><label for="tokenSecret">' + t('once') + '</label>' +
      '<textarea id="tokenSecret" rows="3" readonly spellcheck="false" autocomplete="off"></textarea>' +
      '<div class="actions"><button type="button" class="button secondary" id="tokenCopy">' + t('copy') + '</button>' +
      '<button type="button" class="button secondary" id="tokenHide">' + t('hide') + '</button></div></div>';
    app.appendChild(section);
    var list = section.querySelector('#tokenList'), form = section.querySelector('form');
    var secret = section.querySelector('#tokenSecret'), panel = section.querySelector('#tokenSecretPanel');
    async function refresh() {
      var result = await C.api('GET', '/api/auth/tokens');
      list.innerHTML = result.tokens.length ? result.tokens.map(function (record) {
        return '<article class="list-row"><div><h3>' + e(record.name) + '</h3><p>' + e(record.prefix) + '... | ' +
          e(record.world_id) + '</p><p>' + e(record.scopes.join(', ')) + '</p><p>' + t('expires') + ': ' +
          e(C.date(record.expires_at)) + ' | ' + t('last_used') + ': ' + e(C.date(record.last_used_at) || '-') +
          '</p><p>' + t(record.revoked_at ? 'revoked' : record.active ? 'active' : 'expired') + '</p></div>' +
          (record.active ? '<button type="button" class="button secondary" data-revoke="' + e(record.id) + '">' + t('revoke') + '</button>' : '') + '</article>';
      }).join('') : '<p class="muted">' + t('empty') + '</p>';
    }
    form.onsubmit = async function (event) {
      event.preventDefault();
      var button = form.querySelector('button');
      button.disabled = true;
      var data = new FormData(form);
      try {
        var result = await C.api('POST', '/api/auth/tokens', {
          name: data.get('name'), world_id: data.get('world_id'), scopes: data.getAll('scopes'),
          expires_days: Number(data.get('expires_days')), password: data.get('password')
        });
        secret.value = result.token; panel.hidden = false;
        await refresh();
      } catch (err) { C.error(err); }
      finally { form.elements.password.value = ''; button.disabled = !worlds.length; }
    };
    list.onclick = async function (event) {
      var button = event.target.closest('[data-revoke]');
      if (!button || !window.confirm(window.__('api_tokens.confirm_revoke'))) return;
      button.disabled = true;
      try {
        await C.api('POST', '/api/auth/tokens/revoke', {id: button.dataset.revoke});
        secret.value = ''; panel.hidden = true; await refresh();
      } catch (err) { C.error(err); button.disabled = false; }
    };
    section.querySelector('#tokenHide').onclick = function () { secret.value = ''; panel.hidden = true; };
    section.querySelector('#tokenCopy').onclick = async function () {
      try { await navigator.clipboard.writeText(secret.value); C.toast(window.__('api_tokens.copied')); }
      catch (_) { secret.focus(); secret.select(); C.toast(window.__('api_tokens.copy_manual')); }
    };
    try { await refresh(); } catch (err) { C.error(err); }
  };
})();
