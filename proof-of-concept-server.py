#!/bin/python3
import os, mimetypes, time, json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread, Condition

PORT = 6968
HTTP_REQUEST_TIMEOUT = 20
QUEUE_MSG_TIMEOUT = 60
QUEUE_MSG_COUNT_LIMIT = 500
SESSION_ID = str(time.time_ns())

# Single objects placed in arrays, as a workaround to a problem with accessing the same variable from different threads
http_server = [None]
chat_queue = [None]

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
        self.queue.append({"user": "theodoros_1234_", "user_color": "#FF0000", "message": str(msg), "timestamp": int(time.time()), "mid": self.message_id})
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
    try:
      # Request is for one of the code files
      if self.path == "/script.js" or self.path == "/ui.html" or self.path == "/style.css":
        # Make sure the file exists
        if os.path.exists(self.path[1:]):
          self.send_response(200)                                                         # Response: 200 OK
          self.send_header("Access-Control-Allow-Origin", "http://localhost:"+str(PORT))  # Deny other sites from snooping on our code
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
          new_messages = chat_queue[0].getNewMessages(message_id=request_mid, timeout=HTTP_REQUEST_TIMEOUT)
        else:
          new_messages = chat_queue[0].getNewMessages(timeout=HTTP_REQUEST_TIMEOUT)

        response = {
          "sid": SESSION_ID,
          "messages": new_messages,
        }

        self.send_response(200)                                                         # Response: 200 OK
        self.send_header("Access-Control-Allow-Origin", "http://localhost:"+str(PORT))  # Deny other sites from snooping on our code
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
      print("Connection closed by client", self.client_address)


# HTTP server thread
def HTTPServerThread():
  try:
    with ThreadingHTTPServer(('127.0.0.1', PORT), Response) as server:
      http_server[0] = server
      print("Listening at", PORT)
      server.serve_forever()
  except Exception as e:
    print("HTTP server error:", e)
    exit(1)


if __name__ == "__main__":
  # Create chat queue
  chat_queue[0] = ChatQueue()

  # Start HTTP server
  http_server_thread = Thread(target=HTTPServerThread)
  http_server_thread.start()

  try:
    while True:
      message = input("Enter chat message: ")
      if message == "debug":
        chat_queue[0].debugQueue()
      elif message[:7] == "getpos ":
        print(chat_queue[0].posOfMID(int(message[7:])))
      else:
        chat_queue[0].addMessages(message.split(','))
  except KeyboardInterrupt:
    pass
  except EOFError:
    pass

  # Stop
  print("Stopping")
  http_server[0].shutdown()
