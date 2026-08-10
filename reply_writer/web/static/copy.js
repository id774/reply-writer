// Copy one target to the clipboard, and nothing else on the page.
//
// This is the whole of the JavaScript. No generation is requested from
// here: the API token and the endpoint stay in the server process, and
// the traffic to the generation API always leaves from the server.

(function () {
  "use strict";

  function textOf(element) {
    return element.value !== undefined ? element.value : element.textContent;
  }

  function notify(button, message) {
    var note = button.nextElementSibling;
    if (!note || !note.classList.contains("copied")) {
      note = document.createElement("span");
      note.className = "copied";
      button.parentNode.insertBefore(note, button.nextSibling);
    }
    note.textContent = message;
    window.setTimeout(function () { note.textContent = ""; }, 2000);
  }

  function fallback(button, element) {
    // Keep the text selected so that it can be copied by hand.
    if (element.select) {
      element.select();
    } else {
      var range = document.createRange();
      range.selectNodeContents(element);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
    }
    try {
      if (document.execCommand("copy")) {
        notify(button, "Copied");
        return;
      }
    } catch (error) {
      // Fall through to the manual instruction below.
    }
    notify(button, "Could not copy. Select the text and copy it by hand.");
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) {
      return;
    }

    var copyId = button.getAttribute("data-copy-target");
    if (!copyId) {
      return;
    }

    var element = document.getElementById(copyId);
    if (!element) {
      return;
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(textOf(element)).then(function () {
        notify(button, "Copied");
      }, function () {
        fallback(button, element);
      });
    } else {
      fallback(button, element);
    }
  });
})();
