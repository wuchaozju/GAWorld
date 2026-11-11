/* Pure identity-cue validation and preview; callers insert preview text with textContent. */
(function (root) {
  'use strict';
  var token = '{{identity}}';
  function inspect(settings) {
    settings = settings && typeof settings === 'object' ? settings : {};
    var enabled = settings.enabled === true;
    var view = {enabled:enabled, extraCalls:enabled ? 2 : 0, error:'', a:'', b:''};
    var fields = {}, limits = {template:2000,a:100,b:100};
    Object.keys(limits).forEach(function(key) {
      var raw = settings[key] == null ? '' : settings[key];
      fields[key] = typeof raw === 'string' ? raw.trim() : '';
      if (typeof raw !== 'string' || Array.from(fields[key]).length > limits[key]) view.error = 'length';
    });
    if (!view.error && fields.template.split(token).length !== 2) view.error = 'template';
    if (!view.error && (!fields.a || !fields.b || fields.a === fields.b || fields.a.includes(token) || fields.b.includes(token))) view.error = 'values';
    if (!view.error) {
      view.a = fields.template.replace(token, function(){return fields.a;});
      view.b = fields.template.replace(token, function(){return fields.b;});
    }
    if (!enabled) view.error = '';
    return view;
  }
  var api = {inspect:inspect};
  if (typeof module !== 'undefined') module.exports = api;
  if (root) root.GAWorldIdentityChecks = api;
})(typeof window !== 'undefined' ? window : globalThis);
