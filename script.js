const MESSAGE_TIMEOUT = 10000;
const MESSAGE_REMOVE_ANIMATION_DURATION = 1000;
const MESSAGE_COUNT_MAX = 35;

var img_scale = 1;
var ui_scale = 1;

// DOM
const css_root = document.querySelector(":root");
var chat_container;

// Server communication
const server = new XMLHttpRequest;
server.onload = parseNewMessages;
server.onerror = function() {
  console.warn("Error requesting new messages from server. Retrying in 5s.");
  setTimeout(getNewMessages, 5000);
}
server.ontimeout = function() {
  console.warn("Timed out when requesting new messages from server.");
  getNewMessages();
}
server.timeout = 30000;
var session_id = null;
var last_message_id = null;

// Handle window resizing
function resize() {
  // Change image scaling if needed
  var new_img_scale = Math.ceil(ui_scale * window.devicePixelRatio);
  if (new_img_scale != img_scale) {
    img_scale = new_img_scale;
    console.log("Changed image scale to " + img_scale);
    for (let img of document.getElementsByTagName('img'))
      pickImageScale(img);
  }
}

// URL parameters changed
function urlParamsChange() {
  for (const [key, value] of new URLSearchParams(window.location.hash.substring(1))) {
    if (key == "scale") {
      new_ui_scale = parseFloat(value);
      if (new_ui_scale != ui_scale) {
        ui_scale = new_ui_scale;
        css_root.style.setProperty('--ui-scale', ui_scale);
        resize();
      }
    }
  }
}

// Initialize when the page fully loads
function init() {
  // Get needed DOM elements
  chat_container = document.getElementById("chat-container");
  // Add event handlers
  window.addEventListener("resize", resize);
  window.addEventListener("hashchange", urlParamsChange);
  resize();
  urlParamsChange();
  // Start requesting messages from server
  getNewMessages();
}
window.addEventListener("load", init);

// Requests new messages from server
function getNewMessages() {
  if (session_id != null && last_message_id != null)
    server.open("GET", "get-messages?sid=" + session_id + "&mid=" + last_message_id);
  else
    server.open("GET", "get-messages");
  server.send();
}

// Changes image to appropriate scale
function pickImageScale(img) {
  // Try to pick the wanted scale
  if (img.scales[img_scale] !== undefined) {
    img.src = img.scales[img_scale];
  } else {
    // Otherwise, try to pick another scale
    best_scale = null;
    for (let i of [4, 2, 1]) {
      if (img.scales[i] !== undefined) {
        // If we haven't found anything yet, pick anything we can get
        if (best_scale === null)
          best_scale = img.scales[i];
        // Otherwise, we're more picky and only pick big enough scales
        else if (i >= img_scale)
          best_scale = img.scales[i];
      }
    }
    img.src = best_scale;
  }
}

// Parses and displays new messages received from server
function parseNewMessages() {
  try {
    // Make sure server responded with 200 OK
    if (server.status != 200)
      throw new Error("Server responded with " + server.status + " " + server.statusText);
    // Parse JSON
    let data = JSON.parse(server.responseText);
    // Get session ID
    session_id = data.sid;
    // Go through messages
    for (let msg of data.messages) {
      // Print message to console
      // console.log(msg);

      // Remove oldest messages if we've reached max message limit
      while (chat_container.children.length >= MESSAGE_COUNT_MAX) {
        oldest_message = chat_container.lastElementChild;
        clearTimeout(oldest_message.removal_timeout);
        oldest_message.remove();
      }

      // Create new HTML element, which will contain this message
      // Main div
      let msg_main = document.createElement("div");
      msg_main.classList.add("message");
      // Replying to another message
      if (msg.replying_to_user != undefined && msg.replying_to_message !== undefined) {
        let msg_replying_to = document.createElement("div");
        msg_replying_to.classList.add("replying-to");
        msg_replying_to.textContent = "Replying to @" + msg.replying_to_user + ": " + msg.replying_to_message;
        msg_main.appendChild(msg_replying_to)
      }
      // Badges
      for (let badge of msg['badges']) {
        let msg_badge = new Image();
        msg_badge.classList.add('badge');
        msg_badge.scales = badge;
        pickImageScale(msg_badge);
        msg_main.appendChild(msg_badge);
      }
      // Chatter name
      let msg_user = document.createElement("span");
      msg_user.classList.add("chatter-name");
      msg_user.style.color = msg.user_color;
      msg_user.appendChild(document.createTextNode(msg.user));
      msg_main.appendChild(msg_user);
      // Message text
      msg_main.appendChild(document.createTextNode(": " + msg.message));
      // Put message into main container
      chat_container.prepend(msg_main);
      // Animate
      msg_main.style.setProperty("--message-height", msg_main.clientHeight + "px");
      msg_main.classList.add("message-add");
      // Start timeout for removal of this message
      msg_main.removal_timeout = setTimeout(() => removeMessage(msg_main), MESSAGE_TIMEOUT);

      // Remember the ID of this message, so we don't get it again
      last_message_id = msg.mid;
    }
    // Wait 250ms before checking for messages again
    setTimeout(getNewMessages, 250);
  } catch (error) {
    console.error(error);
    console.error("Error parsing new messages. Retrying in 5s.");
    setTimeout(getNewMessages, 5000);
  }
}

function removeMessage(msg) {
  msg.classList.remove("message-add");
  msg.classList.add("message-remove");
  setTimeout(() => msg.remove(), MESSAGE_REMOVE_ANIMATION_DURATION);
}
