#!/bin/python3
import socket, sys, ssl
from threading import Thread
from queue import Queue

SERVER = None
PORT = None
USERNAME = None
CHANNEL = None
TOKEN = None


# Load config from file
def loadConfig(config_file_path):
  global SERVER, PORT, USERNAME, CHANNEL, TOKEN
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
          if key == "server":
            SERVER = value
          elif key == "port":
            try:
              PORT = int(value)
            except ValueError:
              print("Port must be an integer number.")
              return False
          elif key == "username":
            USERNAME = value
          elif key == "channel":
            CHANNEL = value
          elif key == "token":
            TOKEN = value
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
  for param in [SERVER, PORT, USERNAME, CHANNEL, TOKEN]:
    if param == None:
      print(f"Config file '{config_file_path}' is missing some options.")
      print("Required options are: server, port, channel, token")
      return False
  return True


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
        print("Connection closed by server")
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
        print("Connection closed by server")
        self.connection_open = False
      # Remove part that was sent from buffer
      self._send_buffer = self._send_buffer[bytes_sent:]


if __name__ == "__main__":
  # Load config
  if not loadConfig("server.config"):
    # Exit on error
    exit(1)

  # Print config
  print("Server:", SERVER)
  print("Port:", PORT)
  print("Username:", USERNAME)
  print("Channel:", CHANNEL)
  print("Token:", len(TOKEN) * '*') # OAuth token is censored for security

  # Create SSL/TLS context
  ssl_context = ssl.create_default_context()
  # Connect to server
  with socket.create_connection((SERVER, PORT)) as sock:
    # Wrap socket with SSL/TLS
    with ssl_context.wrap_socket(sock, server_hostname=SERVER) as sock_ssl:
      sock_wrapper = SocketIOWrapper(sock_ssl)
      in_channel = False
      should_disconnect = False
      # Send data to server from console
      try:
        # Log in
        sock_wrapper.sendPrepare(f"PASS oauth:{TOKEN}")
        sock_wrapper.sendPrepare(f"NICK {USERNAME}")
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
              print("Got notice from server:", message.params)
              should_disconnect = True
            elif cmd == "PART":
              # Our account was banned
              print("Banned from channel")
              should_disconnect = True
              in_channel = False;
            elif cmd == "PING":
              # Keeping the connection alive
              sock_wrapper.sendPrepare(f"PONG :{message.params}")
            elif cmd == "PRIVMSG":
              # Message was sent in chat
              print(f"{message.tags['display-name']}: {message.params}")
            elif cmd == "421":
              # We sent a command the server doesn't understand
              print(f"Server didn't recognize a command: {str(message)}")
            elif cmd == "001":
              # Successful login
              print("Logged in")
              # Ask for message tags
              sock_wrapper.sendPrepare(f"CAP REQ twitch.tv/tags")
            elif cmd == "CAP":
              # Extended capabilities
              if message.command[2] == "NAK":
                # Close connection when denied
                print("Extended capabilities denied")
                should_disconnect = True
              elif message.command[2] == "ACK" and message.params == "twitch.tv/tags":
                # Join channel when accepted
                print("Extended capabilities accepted, joining channel")
                sock_wrapper.sendPrepare(f"JOIN #{CHANNEL}")
                in_channel = True

          # Send any queued up commands to server
          sock_wrapper.sendFlush()

      except KeyboardInterrupt:
        print("Closing connection")
      # If we're in the channel, leave it
      if in_channel:
        sock_wrapper.sendPrepare(f"PART #{CHANNEL}")
        sock_wrapper.sendFlush()

# if __name__ == "__main__":
#   try:
#     while True:
#       try:
#         print(parsedIRCMessage(input() + "\r\n"))
#       except ValueError as e:
#         print(e)
#   except KeyboardInterrupt:
#     pass
