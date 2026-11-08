/* Pure validation and budget for synchronous feedback checks. */
(function (root) {
  'use strict';
  function inspect(settings) {
    settings = settings && typeof settings === 'object' ? settings : {};
    var enabled = settings.enabled === true;
    var rounds = settings.rounds === undefined ? 1 : settings.rounds;
    var size = settings.group_size === undefined ? 4 : settings.group_size;
    var valid = Number.isInteger(rounds) && rounds >= 1 && rounds <= 3 &&
      Number.isInteger(size) && size >= 2 && size <= 8;
    return {enabled:enabled,rounds:rounds,groupSize:size,
      extraCalls:enabled && valid ? 4 * rounds : 0,error:enabled && !valid ? 'settings' : ''};
  }
  var api = {inspect:inspect};
  if (typeof module !== 'undefined') module.exports = api;
  if (root) root.GAWorldInteractionChecks = api;
})(typeof window !== 'undefined' ? window : globalThis);
