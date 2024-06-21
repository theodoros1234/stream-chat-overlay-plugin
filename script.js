// DOM Elements
var chat_container;

// Server communication
var server = new XMLHttpRequest;
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
  chat_container = document.getElementById("chat_container");
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
      console.log(msg);
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

