# MicroPyFileSync

This project is designed to send changed files to a MicroPython device via a serial connection.
Designed to automate the upload of changed files in a MicroPython project. Tested on Windows 11 using PyCharm. Significantly decreases development and debugging time.



## Features
- Communication timing optimized
- Notification of difference between device and local file size
- MPY precompile support
- Sending files via raw REPL
- Logging

## Installation

1. Clone the repository:
   ```bash
   https://github.com/aggel80/MicroPyFileSync.git

# Changelog
## v 1.2
- communication timing optimized 
- notification of difference between device and local filesize 
- mpy precompile
## v 1.1
- opening uart output with additional commands 
- sending files via raw repl 
- encoding files in base64 solved problem with sending web_server.h 
- sending by pieces 
- logging
## v 1.0
- this is the first implementation of the program to send files to MicroPython device 
- in the current version implemented checking for changes in files
