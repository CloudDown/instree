/* Bypass interstitial ngrok free sur les requêtes XHR/fetch (si tunnel ngrok). */
(function () {
  var host = String(location.hostname || "");
  if (!/ngrok/i.test(host)) return;

  var HEADER = "ngrok-skip-browser-warning";
  var VALUE = "true";

  var origFetch = window.fetch;
  if (typeof origFetch === "function") {
    window.fetch = function (input, init) {
      init = init ? Object.assign({}, init) : {};
      var headers = new Headers(init.headers || {});
      if (!headers.has(HEADER)) headers.set(HEADER, VALUE);
      init.headers = headers;
      return origFetch.call(this, input, init);
    };
  }

  var XO = window.XMLHttpRequest;
  if (!XO || !XO.prototype) return;
  var origOpen = XO.prototype.open;
  var origSend = XO.prototype.send;
  XO.prototype.open = function () {
    this.__instreeNgrok = true;
    return origOpen.apply(this, arguments);
  };
  XO.prototype.send = function (body) {
    if (this.__instreeNgrok) {
      try {
        this.setRequestHeader(HEADER, VALUE);
      } catch (_) {
        /* headers already sent / unsafe */
      }
    }
    return origSend.call(this, body);
  };
})();
