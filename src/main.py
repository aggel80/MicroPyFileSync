
import re
import serial
import time
import os
import hashlib
import pickle
import logging
import base64
import argparse

STATE_FILE = 'file_state.pkl'
CHUNK_SIZE = 512

def calculate_md5(file_path):
    """Calculates MD5 hash of the file to detect changes."""
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def load_state():
    """Loads the saved state of files from the file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'rb') as f:
            return pickle.load(f)
    return {}

def save_state(state):
    """Saves the state of files to the file."""
    with open(STATE_FILE, 'wb') as f:
        pickle.dump(state, f)

def save_changed_files_state(directory, previous_state):
    """Gets the list of changed files in the specified directory."""
    current_state = {}
    changed_files = []

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            file_md5 = calculate_md5(file_path)
            current_state[file_path] = file_md5

            if file_path not in previous_state or previous_state[file_path] != file_md5:
                changed_files.append(file_path)

    save_state(current_state)
    return changed_files

def get_changed_files(directory, previous_state):
    """Gets the list of changed files in the specified directory."""
    current_state = {}
    changed_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            file_md5 = calculate_md5(file_path)
            current_state[file_path] = file_md5
            if file_path not in previous_state or previous_state[file_path] != file_md5:
                changed_files.append(file_path)
    return changed_files

def send_command(ser, command, wait_for_response=True, timeout=0.2, write_to_read_timeout=0.1):
    """Sends a command and, if required, waits for a response."""
    ser.write(command.encode('utf-8'))
    time.sleep(write_to_read_timeout)
    if wait_for_response:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting).decode('utf-8')
                return response
        return ""
    return None

def enter_raw_repl_mode(ser):
    status = False
    # Enter raw REPL mode
    time.sleep(0.4)
    ser.write(b'\x03')  # Ctrl-C to interrupt any running code
    time.sleep(0.1)
    ser.write(b'\x01')  # Ctrl-A to enter raw REPL
    time.sleep(0.1)
    response = send_command(ser, "\x01", wait_for_response=True)
    if "raw REPL; CTRL-B to exit" not in response:
        print("\033[33mFailed to enter raw REPL mode")
    else:
        status = True
        logger.debug('Entered raw REPL mode')
    return status

def exit_raw_repl_mode(ser):
    status = False
    ser.write(b'\x02')  # Ctrl-B to exit raw REPL

    time.sleep(0.3)
    response = send_command(ser, "\n", wait_for_response=True)
    if "for more information" in response:
        status = True
        logger.debug(f'Exited raw REPL mode {response=}')
        return status
    else:
        print("\033[33mFailed to exit raw REPL mode. Retrying...")
        return status

def send_file_via_raw_repl(ser, base_dir, file_path):
    return_status = False
    try:
        # Get relative path of the file and replace backslashes with forward slashes
        relative_path = os.path.relpath(file_path, base_dir).replace("\\", "/")
        # Open the file for reading in binary mode and encode it in base64
        with open(file_path, 'rb') as file:
            file_content = file.read()
        file_content_base64 = base64.b64encode(file_content).decode('utf-8')
        while not enter_raw_repl_mode(ser):
            time.sleep(0.2)
        logger.debug(f"Time: {time.time() - start_time} s")
        # Create directories on the device
        dirs = os.path.dirname(relative_path).split('/')
        for i in range(1, len(dirs) + 1):
            dir_path = "/".join(dirs[:i])
            response = send_command(ser, f"try:\n import os\n os.mkdir('{dir_path}')\nexcept OSError:\n pass\n",
                                    wait_for_response=True, write_to_read_timeout=0.5)

            if "Traceback" in response:
                print(f"\033[31mError creating directory {dir_path}: {response}")
                return return_status
        logger.debug(f"Time: {time.time() - start_time} s")
        # Prepare to write the file on the device
        ser.write(f"import ubinascii\nwith open('{relative_path}', 'wb') as f:\n".encode('utf-8'))
        response = send_command(ser, '', wait_for_response=True, write_to_read_timeout=0.5)
        logger.debug(f"send file  {response=}")
        time.sleep(0.2)
        # Send the file in chunks
        for i in range(0, len(file_content_base64), CHUNK_SIZE):
            chunk = file_content_base64[i:i + CHUNK_SIZE]
            ser.write(f"    f.write(ubinascii.a2b_base64('''{chunk}'''))\n".encode('utf-8'))
            time.sleep(0.2)  # Small delay for the device to process the data

        # Finish writing the file
        ser.write(b"    f.close()\n")
        response = send_command(ser, '', wait_for_response=True, write_to_read_timeout=0.5)

        logger.debug(f"send file  {response=}")
        logger.debug(f"Time: {time.time() - start_time} s")

        ser.write(b'\x04')  # Ctrl-D to execute the code
        time.sleep(0.1)
        while not exit_raw_repl_mode(ser):
            time.sleep(0.5)

        # ======== check file size part
        local_file_size = os.path.getsize(file_path)

        time.sleep(0.5)
        response = send_command(ser, f"import os\r\nos.stat('{relative_path}')[6]\r\n",
                                wait_for_response=True, timeout=1, write_to_read_timeout=0.5)
        logger.debug(f"file {file_path} size {response=}")
        device_file_size = 0
        if relative_path in response:
            device_file_size = re.split(r'[\r\n]+', response)[2]
        logger.debug(f"{file_path} local size={local_file_size} device file size={device_file_size}")
        if int(local_file_size) != int(device_file_size):
            print(f"\033[31mWarning!!! {file_path} local size={local_file_size} device file size={device_file_size}")
        # ======== check file size part
        else:
            print(f"\033[32mFile {file_path} has been sent successfully.")

        return_status = True
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pass
    return return_status

class Repl:
    def __init__(self):
        self.ser = serial.Serial()

def open_repl_output(ser):
    import threading
    read_from_port_active = True
    def read_from_port(ser):
        while read_from_port_active:
            try:
                raw_data = ser.readline()
                data = raw_data.decode('ansi').strip()
                if data:
                    if "Traceback" in data:
                        print(f"\033[31m{data}")
                    print(f"\033[30m{data}")
            except Exception as e:
                print(f"\033[31mError reading from serial port: {e}")
                break

    threading.Thread(target=read_from_port, args=(ser,), daemon=True).start()
    try:
        ser.write(b'\x04')
        while True:
            # Read input from the user and send it to the serial port
            user_input = input("\033[32mOpening UART output ('x' to quit 'a' to raw repl  'c' to reboot 'd' to reset, 'b' re): \n")
            if user_input.lower() == 'x':
                read_from_port_active = False
                break
            if user_input.lower() == 'c':
                ser.write(b'\x03')
            if user_input.lower() == 'd':
                ser.write(b'\x04')
                print(f"d command")
            if user_input.lower() == 'b':
                ser.write(b'\x02')
            if user_input.lower() == 'a':
                ser.write(b'\x01')
            if user_input == '\x03':  # ASCII code 3 corresponds to CTRL-C
                print("Received CTRL-C key combination")
            ser.write((user_input + '\n').encode('utf-8'))

    except KeyboardInterrupt:
        pass
        print("KeyboardInterrupt")
    finally:
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    DEFAULT_PORT = "COM4"
    DEFAULT_BAUDRATE = 115200
    DEFAULT_BASE_DIR = "src"
    # --port COM3 --baudrate 115200 --base_dir "mpy" --precompile
    parser = argparse.ArgumentParser(description='Script to upload files via serial port.')
    parser.add_argument('--port', type=str, default=DEFAULT_PORT, help=f'Serial port to use (default: {DEFAULT_PORT})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE, help=f'Baud rate for the serial connection (default: {DEFAULT_BAUDRATE})')
    parser.add_argument('--base_dir', type=str, default=DEFAULT_BASE_DIR, help=f'Base directory to watch for changes (default: {DEFAULT_BASE_DIR})')
    parser.add_argument('--precompile', action='store_true', help='Run precompile step before uploading files')
    args = parser.parse_args()
    start_time = time.time()
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.WARNING)  # Set logging level
    # logger.setLevel(logging.DEBUG)  # Set logging level
    console_handler = logging.StreamHandler()
    logger.addHandler(console_handler)
    port = args.port
    baudrate = args.baudrate
    base_dir = args.base_dir
    if args.precompile:
        from makempy import run_precompile
        run_precompile()
    previous_state = load_state()
    changed_files = get_changed_files(base_dir, previous_state)

    if changed_files:
        print(f'Changed files: {changed_files}')
    ser = serial.Serial(port, baudrate, timeout=1)
    print(f"Connected to {port} at {baudrate} baud rate.")
    if changed_files:
        for file_path in changed_files:
            if send_file_via_raw_repl(ser, base_dir, file_path):
                save_changed_files_state(base_dir, previous_state)
    else:
        print("\033[33mThe files were not modified.")
    logger.debug(f"Time: {time.time() - start_time} s")
    open_repl_output(ser)
