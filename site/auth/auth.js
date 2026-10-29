
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); }, params = new URLSearchParams(location.search);
  var mode = location.pathname.replace(/\/+$/, '').split('/').pop(), next = params.get('next') || '/console#workspace';
  if (!/^\/(?![\/\\])/.test(next) || /[\u0000-\u0020\\]/.test(next)) next = '/console#workspace';
  if (location.hash && next.indexOf('#') < 0) next += location.hash;
  var code = params.get('code') || '', open = false;
  $('form').onsubmit = function (event) { event.preventDefault(); };
  $('submit').disabled = true;
  async function api(path, data) {
    var r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    var d = await r.json(); if (!r.ok) throw new Error(d.error || '操作失败'); return d;
  }
  var settings = {
    login: ['登录 GAWorld', '用用户名和密码登录。', '登录', '/api/auth/login'],
    join: ['注册', '使用邀请码注册，密码至少 8 位。', '注册并登录', '/api/auth/register'],
    register: ['创建你的研究账号', '注册后验证邮箱，开始自己的研究与仿真。', '注册并发送验证邮件', '/api/auth/register'],
    reset: ['重设密码', '使用管理员提供的一次性重置码。', '重设并登录', '/api/auth/reset'],
    recover: ['找回密码', code ? '设置新密码，其他会话会同时退出。' : '输入注册邮箱，接收密码重设链接。', code ? '重设密码' : '发送重设链接', code ? '/api/auth/recover/reset' : '/api/auth/recover'],
    verify: ['验证邮箱', '确认邮箱后，可以开展研究、发布成果并参与讨论。', '确认验证', '/api/auth/verify']
  };
  if (!settings[mode]) mode = 'login';
  function render() {
    if (mode === 'register' && !open) mode = 'join';
    var cfg = settings[mode], registration = mode === 'register', password = mode !== 'verify' && !(mode === 'recover' && !code);
    $('title').textContent = cfg[0]; $('hint').textContent = cfg[1]; $('submit').textContent = cfg[2]; document.title = 'GAWorld · ' + cfg[0];
    $('nickname-row').hidden = !['login','join','register'].includes(mode);
    $('nickname').required = !$('nickname-row').hidden;
    var nicknameLabel = document.querySelector('label[for="nickname"]'); nicknameLabel.textContent = mode === 'join' ? '昵称（登录名）' : '用户名';
    $('code-row').hidden = !['join','reset'].includes(mode); $('code-label').textContent = mode === 'reset' ? '重置码' : '邀请码'; $('code').value = code;
    $('email-row').hidden = !(registration || (mode === 'recover' && !code)); $('email').required = !$('email-row').hidden;
    $('display-row').hidden = !registration;
    $('password-row').hidden = !password; $('password').required = password;
    $('password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    $('confirm-row').hidden = !(registration || mode === 'join' || mode === 'reset' || (mode === 'recover' && code));
    $('confirm').required = !$('confirm-row').hidden;
    $('to-join').hidden = mode !== 'login'; $('to-join').href = gwURL(open ? '/register' : '/join'); $('to-join').textContent = open ? '创建账号' : '有邀请码？注册';
    $('to-reset').hidden = mode !== 'login'; $('to-reset').href = gwURL(open ? '/recover' : '/reset'); $('to-reset').textContent = open ? '忘记密码？' : '有重置码？重设密码';
    $('to-login').hidden = mode === 'login';
    $('form').onsubmit = async function (event) {
      event.preventDefault(); $('submit').disabled = true; $('error').textContent = '';
      try {
        if (!$('confirm-row').hidden && $('confirm').value !== $('password').value) throw new Error('两次输入的密码不一致');
        var body = { nickname:$('nickname').value.trim(),password:$('password').value,code:$('code').value.trim() || code,email:$('email').value.trim(),display_name:$('display_name').value.trim() };
        await api(cfg[3], body);
        if (mode === 'recover') { $('hint').textContent = code ? '密码已修改，请登录。' : '若邮箱符合条件，重设邮件已发送，请检查收件箱。'; $('form').hidden = true; $('to-login').hidden = false; return; }
        location.replace(gwURL(next));
      } catch (err) { $('error').textContent = err.message; $('submit').disabled = false; }
    };
    $('submit').disabled = false;
  }
  fetch('/api/auth/config').then(function (r) { return r.json(); }).then(function (cfg) { open = cfg.registration === 'open'; render(); }).catch(render);
})();
