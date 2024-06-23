#!/bin/python3
import socket, sys, ssl
from threading import Thread

SERVER = None
PORT = None
CHANNEL = None
TOKEN = None


# Load config from file
def loadConfig(config_file_path):
  global SERVER, PORT, CHANNEL, TOKEN
  try:
    with open(config_file_path, 'r') as config_file:
      for line in config_file.readlines():
        # Remove newline and/or carriage return
        line = line.removesuffix('\n').removesuffix('\r')
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
  for param in [SERVER, PORT, CHANNEL, TOKEN]:
    if param == None:
      print(f"Config file '{config_file_path}' is missing some options.")
      print("Required options are: server, port, channel, token")
      return False
  return True


def socketReceiver(sock):
  print("Receiver thread started")
  while True:
    chunk = sock.recv(4096)
    if len(chunk) == 0:
      print("Connection closed")
      return
    sys.stdout.write(chunk.decode('utf-8'))

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

    print()
    print("Tags:", tags_segment)
    print("Prefix:", prefix_segment)
    print("Command:", command_segment)
    print("Params:", params_segment)
    print()


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


# if __name__ == "__main__":
#   # Load config
#   if not loadConfig("server.config"):
#     # Exit on error
#     exit(1)
#
#   # Print config
#   print("Server:", SERVER)
#   print("Port:", PORT)
#   print("Channel:", CHANNEL)
#   print("Token:", len(TOKEN) * '*') # OAuth token is censored for security
#
#   # Create SSL/TLS context
#   ssl_context = ssl.create_default_context()
#   # Connect to server
#   with socket.create_connection((SERVER, PORT)) as sock:
#     # Wrap socket with SSL/TLS
#     with ssl_context.wrap_socket(sock, server_hostname=SERVER) as sock_ssl:
#       # Receiver thread
#       Thread(target=socketReceiver, args=(sock_ssl,)).start()
#       # Send data to server from console
#       try:
#         while True:
#           msg = input() + "\r\n"
#           sock_ssl.send(msg.encode('utf-8'))
#       except EOFError:
#         print("Closing connection")
#       except KeyboardInterrupt:
#         print("Closing connection")

if __name__ == "__main__":
  try:
    while True:
      try:
        print(parsedIRCMessage(input() + "\r\n"))
      except ValueError as e:
        print(e)
  except KeyboardInterrupt:
    pass
