/* Phone pass page: purely local, sends nothing to any server. Texts from i18n.js. */
"use strict";
const $ = (id) => document.getElementById(id);
let createdAt = null;
function showTime() { if (createdAt) $("pass-time").textContent = tr("ph.created", { time: createdAt }); }
$("ph-go").addEventListener("click", () => {
  let code = $("ph-code").value.toUpperCase().replace(/\s+/g, "");
  if (/^[A-Z0-9]{6}$/.test(code)) code = code.slice(0, 3) + "-" + code.slice(3);
  const ch = $("ph-ch").value.toUpperCase().replace(/\s+/g, "");
  if (!code || !ch) return;
  $("pass-code").textContent = code;
  $("pass-ch").textContent = ch;
  createdAt = new Date().toLocaleTimeString("de-DE");
  showTime();
  $("ph-form").hidden = true;
  $("ph-pass").hidden = false;
});
$("ph-back").addEventListener("click", () => { $("ph-form").hidden = false; $("ph-pass").hidden = true; });
document.addEventListener("langchange", showTime);
