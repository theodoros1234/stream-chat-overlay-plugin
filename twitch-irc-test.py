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

if __name__ == "__main__":
  # Load config
  if not loadConfig("server.config"):
    # Exit on error
    exit(1)

  # Print config
  print("Server:", SERVER)
  print("Port:", PORT)
  print("Channel:", CHANNEL)
  print("Token:", len(TOKEN) * '*') # OAuth token is censored for security

  # Create SSL/TLS context
  ssl_context = ssl.create_default_context()
  # Connect to server
  with socket.create_connection((SERVER, PORT)) as sock:
    # Wrap socket with SSL/TLS
    with ssl_context.wrap_socket(sock, server_hostname=SERVER) as sock_ssl:
      # Receiver thread
      Thread(target=socketReceiver, args=(sock_ssl,)).start()
      # Send data to server from console
      try:
        while True:
          msg = input() + "\r\n"
          sock_ssl.send(msg.encode('utf-8'))
      except EOFError:
        print("Closing connection")
      except KeyboardInterrupt:
        print("Closing connection")
