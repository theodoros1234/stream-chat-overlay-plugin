#!/bin/python3
import os, mimetypes, time, json, socket, sys, ssl, random, requests
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread, Condition
from queue import Queue

SESSION_ID = str(time.time_ns())
LOCAL_PORT = None
HTTP_REQUEST_TIMEOUT = None
QUEUE_MSG_TIMEOUT = None
QUEUE_MSG_COUNT_LIMIT = None
IRC_SERVER = None
IRC_PORT = None
CHANNEL = None
OAUTH_TOKEN = None

http_server = None
chat_queue = None
oauth_client_id = None
user_id = None
username = None
channel_id = None


# Load config from file
def loadConfig(config_file_path):
  global LOCAL_PORT, HTTP_REQUEST_TIMEOUT, QUEUE_MSG_TIMEOUT, QUEUE_MSG_COUNT_LIMIT, IRC_SERVER, IRC_PORT, CHANNEL, OAUTH_TOKEN
  def parseIntValue(key, val):
    try:
      return int(value)
    except ValueError:
      print(f"{key} must be an integer number.")
      return None

  try:
    with open(config_file_path, 'r') as config_file:
      for line in config_file.readlines():
        # Remove newline and/or carriage return
        line = line.removesuffix('\n').removesuffix('\r')
        # Ignore lines that start with #
        if len(line)>1 and line[0] == '#':
          continue
        # Split line to key and value
        separator = line.find('=')
        if separator != -1:
          key = line[:separator]
          value = line[separator+1:]
          # Determine if it's a value we want, and grab it
          if key == "irc-server":
            IRC_SERVER = value
          elif key == "irc-port":
            IRC_PORT = parseIntValue(key, value)
            if IRC_PORT == None:
              return False
          elif key == "channel":
            CHANNEL = value
          elif key == "oauth-token":
            OAUTH_TOKEN = value
          elif key == "local-port":
            LOCAL_PORT = parseIntValue(key, value)
            if LOCAL_PORT == None:
              return False
          elif key == "http-request-timeout":
            HTTP_REQUEST_TIMEOUT = parseIntValue(key, value)
            if HTTP_REQUEST_TIMEOUT == None:
              return False
          elif key == "queue-msg-timeout":
            QUEUE_MSG_TIMEOUT = parseIntValue(key, value)
            if QUEUE_MSG_TIMEOUT == None:
              return False
          elif key == "queue-msg-count-limit":
            QUEUE_MSG_COUNT_LIMIT = parseIntValue(key, value)
            if QUEUE_MSG_COUNT_LIMIT == None:
              return False
          else:
            print(f"Unknown option '{key}' found in config file '{config_file_path}'.")
  # Handle common file errors
  except FileNotFoundError:
    print(f"Could not find config file '{config_file_path}'.")
    return False
  except PermissionError:
    print(f"Permission denied for config file '{config_file_path}'.")
    return False
  # Make sure we got all the requred parameters
  for param in [LOCAL_PORT, HTTP_REQUEST_TIMEOUT, QUEUE_MSG_TIMEOUT, QUEUE_MSG_COUNT_LIMIT, IRC_SERVER, IRC_PORT, CHANNEL, OAUTH_TOKEN]:
    if param == None:
      print(f"Config file '{config_file_path}' is missing some options.")
      print("Required options are: local-port, http-request-timeout, queue-msg-timeout, queue-msg-count-limit, irc-server, irc-port, channel, oauth-token")
      return False
  return True


# Chat queue
class ChatQueue():
  def __init__(self):
    self.queue = []
    self.message_id = 0
    self.oldest_message_id = 0
    self.lock = Condition()
    Thread(target=self._timeoutMessages, daemon=True).start()

  # Adds messages to queue
  def addMessages(self, msg_list):
    with self.lock:
      messages_added = False
      for msg in msg_list:
        # Remove message if queue is full
        while len(self.queue) >= QUEUE_MSG_COUNT_LIMIT:
          self.queue.remove(self.queue[0])
          self.oldest_message_id += 1
        # Add message to queue
        msg_for_queue = msg.copy()
        msg_for_queue["timestamp"] = int(time.time())
        msg_for_queue["mid"] = self.message_id
        self.queue.append(msg_for_queue)
        self.message_id += 1
        # Mark that at least one new message was added
        messages_added = True
      # Wake up threads waiting for new messages
      self.lock.notify_all()

  # Automatically removes messages from queue
  def _timeoutMessages(self):
    target_time = 0
    while True:
      oldest_message_timestamp = None
      with self.lock:
        # Remove all expired messages
        target_time = int(time.time()) - QUEUE_MSG_TIMEOUT
        while len(self.queue) > 0 and self.queue[0]["timestamp"] <= target_time:
          self.queue.remove(self.queue[0])
          self.oldest_message_id += 1
        # If queue is empty, wait until there's an item to remove
        while len(self.queue) == 0:
          self.lock.wait()
        oldest_message_timestamp = self.queue[0]["timestamp"]
      # Wait until it's time to remove the oldest message
      wait_for = oldest_message_timestamp + QUEUE_MSG_TIMEOUT + 1 - time.time()
      if wait_for > 0:
        time.sleep(wait_for)

  # Gets the position in the array of given message ID
  # Queue must be locked by calling function
  # Returns -1 if the message expired, None if message hasn't been received yet, or position of message in array
  def _posOfMID(self, message_id):
    if message_id < self.oldest_message_id:
      return -1
    elif message_id >= self.message_id:
      return None
    else:
      return message_id - self.oldest_message_id

  # Same as above, but locks queue, so it can be safely called externally
  def posOfMID(self, message_id):
    with self.lock:
      return self._posOfMID(message_id)

  # Returns new messages from queue after message ID or waits for new messages if there aren't any
  def getNewMessages(self, message_id=None, timeout=None):
    assert type(message_id) == int or message_id == None
    with self.lock:
      # Ignore pre-existing messages if message id was not given or is out of bounds
      if message_id == None or message_id < -1 or message_id >= self.message_id:
        message_id = self.message_id - 1
      # Wait for new messages to arrive, if there weren't any or all of them expired
      if self._posOfMID(message_id + 1) == None or len(self.queue) == 0:
        if not self.lock.wait(timeout):
          # Return empty list on timeout
          return []
      # Get new messages (if there are any)
      start_from = self._posOfMID(message_id) + 1
      new_messages = []
      assert start_from != None
      for i in range(start_from, len(self.queue)):
        new_messages.append(self.queue[i])
      return new_messages

  # Prints current queue state to console
  def debugQueue(self):
    with self.lock:
      print("message_id:", self.message_id)
      print("queue:", self.queue)


# HTTP request handler
class Response(BaseHTTPRequestHandler):
  def do_GET(self):
    global chat_queue
    try:
      # Request is for one of the code files
      if self.path == "/script.js" or self.path == "/ui.html" or self.path == "/style.css":
        # Make sure the file exists
        if os.path.exists(self.path[1:]):
          self.send_response(200)                                                         # Response: 200 OK
          self.send_header("Access-Control-Allow-Origin", "http://localhost:"+str(LOCAL_PORT))  # Deny other sites from snooping on our code
          self.send_header("Content-Type", mimetypes.guess_type(self.path)[0])            # Figure out what file type we're sending
          self.end_headers()

          with open(self.path[1:], "rb") as f:
            self.wfile.write(f.read())

        # 404 Not Found if the file doesn't exist
        else:
          self.send_response(404)     # Response: 404 Not Found
          self.end_headers()
          self.wfile.write(b"404 Not Found")

      # Request for chat messages
      elif self.path == "/get-messages" or self.path[:14] == "/get-messages?":
        request_sid = None
        request_mid = None
        new_messages = None
        if len(self.path) > 13 and self.path[13] == '?' and len(self.path) <= 100:
          # Parse SID and MID from path
          items = self.path[14:].split('&')
          for item in items:
            try:
              separator = item.find("=")
              if separator != -1:
                key = item[:separator]
                value = item[separator+1:]
                if key == "sid":
                  request_sid = value
                elif key == "mid":
                  request_mid = int(value)
            except:
              pass

        if request_sid == SESSION_ID:
          new_messages = chat_queue.getNewMessages(message_id=request_mid, timeout=HTTP_REQUEST_TIMEOUT)
        else:
          new_messages = chat_queue.getNewMessages(timeout=HTTP_REQUEST_TIMEOUT)

        response = {
          "sid": SESSION_ID,
          "messages": new_messages,
        }

        self.send_response(200)                                                         # Response: 200 OK
        self.send_header("Access-Control-Allow-Origin", "http://localhost:"+str(LOCAL_PORT))  # Deny other sites from snooping on our code
        self.send_header("Content-Type", "application/json")                            # Responding in JSON
        self.end_headers()

        # Send response in JSON
        self.wfile.write(json.dumps(response).encode('utf-8'))

      # Request for non-existent path
      else:
        self.send_response(404)     # Response: 404 Not Found
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    except BrokenPipeError:
      print("[Local HTTP] Connection closed by client", self.client_address)


class parsedIRCMessage():
  def __init__(self, raw_message):
    # Check for correct type
    if type(raw_message) != str:
      raise TypeError("Message must be a string")

    tags_segment = None
    prefix_segment = None
    command_segment = None
    params_segment = None
    start = 0
    end = 0

    self.tags = None
    self.nickname = None
    self.username = None
    self.server = None
    self.command = []
    self.params = None

    # Get tags, if any
    if raw_message[start] == '@':
      end = raw_message.find(' ', start)
      if end == -1:
        raise ValueError("Invalid IRC command syntax: End of tags section is missing")
      tags_segment = raw_message[start+1:end]
      start = end + 1

      # Parse tags
      self.tags = {}
      for tag in tags_segment.split(';'):
        separator = tag.find('=')
        if separator == -1:
          # Key with no value
          self.tags[tag] = None
        else:
          # Key with value
          key = tag[:separator]
          value = tag[separator+1:]
          # Convert escape codes
          value = value.replace('\\:', ';')\
                       .replace('\\s', ' ')\
                       .replace('\\\\', '\\')\
                       .replace('\\r', '\r')\
                       .replace('\\n', '\n')
          self.tags[key] = value

    # Get prefix, if defined
    if raw_message[start] == ':':
      end = raw_message.find(' ', start)
      if end == -1:
        raise ValueError("Invalid IRC command syntax: End of prefix section is missing")
      prefix_segment = raw_message[start+1:end]
      start = end + 1

      # Parse prefix
      user_start = prefix_segment.find('!')
      host_start = prefix_segment.find('@')
      if user_start == host_start == -1:
        self.server = prefix_segment
      else:
        if user_start == -1:    # username not defined, so host is defined
          self.nickname = prefix_segment[:host_start]
          self.server = prefix_segment[host_start+1:]
        else:                   # username defined
          self.nickname = prefix_segment[:user_start]
          if host_start == -1:  # but host not defined
            self.username = prefix_segment[user_start+1:]
          else:                 # all 3 defined
            self.username = prefix_segment[user_start+1:host_start]
            self.server = prefix_segment[host_start+1:]

    # Get command, channel and acknowledgement
    # There are either parameters or the end of line after the command segment
    end = raw_message.find(':', start)
    if end == -1:
      end = raw_message.find('\r\n', start)
    if end == -1:
      raise ValueError("Invalid IRC command syntax: End of message not found")
    command_segment = raw_message[start:end-1]
    start = end
    self.command = command_segment.split(' ')

    # Get parameters, if any
    if raw_message[start] == ':':
      end = raw_message.find('\r\n', start)
      if end == -1:
        raise ValueError("Invalid IRC command syntax: End of message not found")
      params_segment = raw_message[start+1:end]
      self.params = params_segment


  def __str__(self):
    d = {
      "tags": self.tags,
      "nickname": self.nickname,
      "username": self.username,
      "server": self.server,
      "command": self.command,
      "params": self.params
    }
    return str(d)


# Socket IO wrapper that handles sending and receiving messages from server
class SocketIOWrapper():
  def __init__(self, sock):
    self._sock = sock
    self._receive_buffer = b""
    self._send_buffer = b""
    self.incoming_message_queue = Queue()
    self.connection_open = True

  # Receive new data from socket
  def receive(self):
    # Grab new data from socket
    if self.connection_open:
      chunk = self._sock.recv(4096)
      # Check if connection closed
      if len(chunk) == 0:
        print("[Twitch IRC] Connection closed by server")
        self.connection_open = False
      # Push to buffer, and check if any full messages were received
      self._receive_buffer += chunk
      eol = self._receive_buffer.find(b'\r\n')
      while eol != -1:
        self.incoming_message_queue.put(self._receive_buffer[:eol+2].decode('utf-8'))
        self._receive_buffer = self._receive_buffer[eol+2:]
        eol = self._receive_buffer.find(b'\r\n')

  # Put message to send buffer, so it can be sent later
  def sendPrepare(self, message):
    self._send_buffer += (message + "\r\n").encode('utf-8')

  # Send buffered messages to server, making sure everything was sent
  def sendFlush(self):
    while self.connection_open and len(self._send_buffer) > 0:
      bytes_sent = self._sock.send(self._send_buffer)
      # Check if conneciton is closed
      if bytes_sent == 0:
        print("[Twitch IRC] Connection closed by server")
        self.connection_open = False
      # Remove part that was sent from buffer
      self._send_buffer = self._send_buffer[bytes_sent:]


# HTTP server thread
def HTTPServerThread():
  global http_server
  try:
    with ThreadingHTTPServer(('127.0.0.1', LOCAL_PORT), Response) as server:
      http_server = server
      print("[Local HTTP] Listening at", LOCAL_PORT)
      server.serve_forever()
  except Exception as e:
    print("[Local HTTP] Exception:", e)
    exit(1)


# Debug message source, which gets messages from terminal instead of Twitch
def consoleMessageSource():
  global chat_queue
  try:
    while True:
      message = input("Enter chat message: ")
      if message == "debug":
        chat_queue.debugQueue()
      elif message[:7] == "getpos ":
        print(chat_queue.posOfMID(int(message[7:])))
      else:
        chat_queue.addMessages({
          "user": "theodoros_1234_",
          "user_color": "#FF0000",
          "message": message
        })
  except KeyboardInterrupt:
    pass
  except EOFError:
    pass


# Converts hexadecimal color to corresponding terminal ANSI escape code
def hexToANSIColorWrap(hex_color, text):
  # Return uncolored string on wrong type or size
  if type(hex_color) != str or len(hex_color) != 7 or hex_color[0] != "#":
    return text
  # Try to get RGB values, or return uncolored string on value error
  try:
    r = int(hex_color[1:3], base=16)
    g = int(hex_color[3:5], base=16)
    b = int(hex_color[5:7], base=16)
  except ValueError:
    return text
  # Convert to ANSI escape code
  return f"\033[38;2;{str(r)};{str(g)};{str(b)}m{text}\033[0m"


# Checks if Twitch OAuth token is valid and gets required info about it
# Returns True/False based on validity of token and required scopes
def twitchValidateToken():
  global OAUTH_TOKEN, oauth_client_id, username, user_id
  r = requests.get("https://id.twitch.tv/oauth2/validate", headers={'Authorization': f"OAuth {OAUTH_TOKEN}"})
  # Invalid token
  if r.status_code == 401:
    print("[Twitch API] OAuth token is invalid")
    return False
  elif r.status_code != 200:
    print(f"[Twitch API] Could not check validity of OAuth token: Server responded with {str(r.status_code)} status code")
  # Parse JSON
  r_values = r.json()
  # Check for required scope
  if not "chat:read" in r_values['scopes']:
    print("[Twitch API] OAuth token is missing scope 'chat:read'")
    return False
  # Parse info
  oauth_client_id = r_values['client_id']
  username = r_values['login']
  user_id = r_values['user_id']
  return True


def twitchGetIDOfUser(username):
  global OAUTH_TOKEN, oauth_client_id
  headers = {
    "Authorization": f"Bearer {OAUTH_TOKEN}",
    "Client-Id": oauth_client_id
  }
  r = requests.get("https://api.twitch.tv/helix/users", headers=headers, params={"login": username})
  # Unauthorized or bad request
  if r.status_code != 200:
    print(f"[Twitch API] Could not get user ID: Server responded with {str(r.status_code)} status code")
    return
  # Parse info
  r_values = r.json()
  # No value returned
  if len(r_values['data']) == 0:
    print(f"[Twitch API] Could not get user ID: Server responded with no data")
    return
  return r_values['data'][0]['id']


# Gets Twitch global and channel chat badges
def twitchGetChatBadges():
  global CHANNEL, oauth_client_id, OAUTH_TOKEN
  # Auth headers
  headers = {
    'Authorization': f"Bearer {OAUTH_TOKEN}",
    'Client-Id': oauth_client_id
  }
  # Get global and channel badges
  r_global_badges = requests.get("https://api.twitch.tv/helix/chat/badges/global", headers=headers)
  if r_global_badges.status_code != 200:
    print(f"[Twitch API] Could not get global chat badges. Server responded with {str(r_global_badges.status_code)}")
    return
  r_channel_badges = requests.get("https://api.twitch.tv/helix/chat/badges", headers=headers, params={'broadcaster_id': channel_id})
  if r_channel_badges.status_code != 200:
    print(f"[Twitch API] Could not get channel chat badges. Server responded with {str(r_channel_badges.status_code)}")
    return

  # Parse badge info
  badges = {}
  for badge_info in r_global_badges.json()['data'] + r_channel_badges.json()['data']:
    # Badge category level (e.g. subscriber, bits, etc.)
    # Create category in local database if it doesn't exist
    if not badge_info['set_id'] in badges:
      badges[badge_info['set_id']] = dict()
    # Go through all versions
    for badge_version_info in badge_info['versions']:
      # Badge version level (e.g. 6-month sub badge)
      badge_version = dict()
      # 1x, 2x and 4x scale versions of this badge version
      badge_version[1] = badge_version_info['image_url_1x']
      badge_version[2] = badge_version_info['image_url_2x']
      badge_version[4] = badge_version_info['image_url_4x']
      badges[badge_info['set_id']][badge_version_info['id']] = badge_version
  return badges


# Twitch IRC message source
def twitchIRCMessageSource():
  global IRC_SERVER, IRC_PORT, username, CHANNEL, OAUTH_TOKEN, chat_queue, channel_id
  # Set and keep track of colors for chatters that didn't set theirs
  uncolored_chatters = dict()
  # Validate Twitch OAuth token
  if not twitchValidateToken():
    return 2
  print(f"[Twitch API] Logged in as {username} with UID {user_id}")
  # Get channel ID
  channel_id = twitchGetIDOfUser(CHANNEL)
  if channel_id == None:
    return 2
  print(f"[Twitch API] Got channel ID {channel_id}")
  # Get channel badges
  badges = twitchGetChatBadges()
  if badges == None:
    return 3
  # Create SSL/TLS context
  ssl_context = ssl.create_default_context()
  # Connect to server
  with socket.create_connection((IRC_SERVER, IRC_PORT)) as sock:
    # Wrap socket with SSL/TLS
    with ssl_context.wrap_socket(sock, server_hostname=IRC_SERVER) as sock_ssl:
      sock_wrapper = SocketIOWrapper(sock_ssl)
      in_channel = False
      should_disconnect = False
      for_local_chat_queue = []
      # Send data to server from console
      try:
        # Log in
        sock_wrapper.sendPrepare(f"PASS oauth:{OAUTH_TOKEN}")
        sock_wrapper.sendPrepare(f"NICK {username}")
        sock_wrapper.sendFlush()

        # Listen to server's messages
        while (sock_wrapper.connection_open and not should_disconnect) or not sock_wrapper.incoming_message_queue.empty():
          # Receive new messages
          sock_wrapper.receive()

          # Process any new messages
          while not sock_wrapper.incoming_message_queue.empty():
            message = parsedIRCMessage(sock_wrapper.incoming_message_queue.get())
            #print(message)
            cmd = message.command[0]
            if cmd == "NOTICE":
              # Authentication failed, likely
              print("[Twitch IRC] Got notice from server:", message.params)
              should_disconnect = True

            elif cmd == "PART":
              # Our account was banned
              print("[Twitch IRC] Banned from channel")
              should_disconnect = True
              in_channel = False;

            elif cmd == "PING":
              # Keeping the connection alive
              sock_wrapper.sendPrepare(f"PONG :{message.params}")

            elif cmd == "PRIVMSG":
              # Message was sent in chat
              # Give color to chatters that didn't set theirs
              if not 'color' in message.tags or message.tags['color'] == "":
                # Only generate color if we haven't already from previous messages
                if not message.username in uncolored_chatters:
                  # Keep generating colors, until we get one that's bright enough
                  readability = 0
                  while readability < 255:
                    r = random.randrange(256)
                    g = random.randrange(256)
                    b = random.randrange(256)
                    readability = r*1.33 + g*2 + b
                  # Remember this color for later
                  uncolored_chatters[message.username] = "#%02X%02X%02X" % (r, g, b)
                # Get saved color
                message.tags['color'] = uncolored_chatters[message.username]
              # Use username as display name when the user didn't set theirs
              if not 'display-name' in message.tags or message.tags['display-name'] == "":
                message.tags['display-name'] = message.username
              # Print message to console
              print(f"{hexToANSIColorWrap(message.tags['color'], message.tags['display-name'])}: {message.params}")
              # Get needed info from this message
              needed_msg_info = {
                'user': message.tags['display-name'],
                'user_color': message.tags['color'],
                'badges': []
              }
              # Handle replies
              if 'reply-parent-display-name' in message.tags and 'reply-parent-msg-body' in message.tags:
                # Message is a reply
                needed_msg_info['replying_to_user'] = message.tags['reply-parent-display-name']
                needed_msg_info['replying_to_message'] = message.tags['reply-parent-msg-body']
                # Cut out @user-being-replied-to from message
                needed_msg_info['message'] = message.params[message.params.find(' ')+1:]
              else:
                # Normal message (not reply)
                needed_msg_info['message'] = message.params
              # Handle badges
              if 'badges' in message.tags and message.tags['badges'] != "":
                for badge in message.tags['badges'].split(','):
                  badge_info = badge.split('/')
                  try:
                    needed_msg_info['badges'].append(badges[badge_info[0]][badge_info[1]])
                  except KeyError as e:
                    # Silently ignore unknown badges
                    print("[Twitch IRC] Unknown badge:", badge_info[0], badge_info[1])
              # Append message to local chat queue
              for_local_chat_queue.append(needed_msg_info)

            elif cmd == "421":
              # We sent a command the server doesn't understand
              print(f"[Twitch IRC] Server didn't recognize a command: {str(message)}")

            elif cmd == "001":
              # Successful login
              print("[Twitch IRC] Logged in")
              # Ask for message tags
              sock_wrapper.sendPrepare(f"CAP REQ twitch.tv/tags")

            elif cmd == "CAP":
              # Extended capabilities
              if message.command[2] == "NAK":
                # Close connection when denied
                print("[Twitch IRC] Extended capabilities denied")
                should_disconnect = True
              elif message.command[2] == "ACK" and message.params == "twitch.tv/tags":
                # Join channel when accepted
                print("[Twitch IRC] Extended capabilities accepted, joining channel")
                sock_wrapper.sendPrepare(f"JOIN #{CHANNEL}")
                in_channel = True

          # Send any queued up commands to server
          sock_wrapper.sendFlush()
          # Add any received messages to local message queue
          if len(for_local_chat_queue) > 0:
            chat_queue.addMessages(for_local_chat_queue)
            for_local_chat_queue = []

      except KeyboardInterrupt:
        print("[Twitch IRC] Closing connection")
      # If we're in the channel, leave it
      if in_channel:
        sock_wrapper.sendPrepare(f"PART #{CHANNEL}")
        sock_wrapper.sendFlush()
  return 0

if __name__ == "__main__":
  # Load config
  if not loadConfig("server.config"):
    # Exit on invalid config
    exit(1)
  # Print config to console
  print("Session ID:", SESSION_ID)
  print("Local port:", LOCAL_PORT)
  print("HTTP request timeout:", HTTP_REQUEST_TIMEOUT)
  print("Queue message timeout:", QUEUE_MSG_TIMEOUT)
  print("Queue message count limit:", QUEUE_MSG_COUNT_LIMIT)
  print("IRC Server:", IRC_SERVER)
  print("IRC Port:", IRC_PORT)
  print("OAuth Token:", len(OAUTH_TOKEN)*'*')   # Censor token for security
  print()


  # Create chat queue
  chat_queue = ChatQueue()
  # Start HTTP server
  http_server_thread = Thread(target=HTTPServerThread)
  http_server_thread.start()
  # Start Twitch IRC client
  exit_code = twitchIRCMessageSource()

  # Stop
  print("[Local HTTP] Stopping")
  http_server.shutdown()
  exit(exit_code)

