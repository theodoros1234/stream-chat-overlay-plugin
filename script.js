const MESSAGE_TIMEOUT = 10000;
const MESSAGE_REMOVE_ANIMATION_DURATION = 1000;
const MESSAGE_COUNT_MAX = 35;

// DOM Elements
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

// Initialize when the page fully loads
function init() {
  // Get needed DOM elements
  chat_container = document.getElementById("chat-container");
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
      console.log(msg);

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
