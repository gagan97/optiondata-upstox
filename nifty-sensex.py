import threading
import subprocess
import os

def run_script(script_name):
    try:
        print(f"Starting {script_name}...")
        result = subprocess.run(['python3', script_name], capture_output=True, text=True)
        print(f"Output of {script_name}:\n{result.stdout}")
        if result.stderr:
            print(f"Errors in {script_name}:\n{result.stderr}")
        print(f"{script_name} finished.")
    except Exception as e:
        print(f"Failed to run {script_name}: {e}")

# Define the directory where the scripts are located
script_directory = '/home/ubuntu/optiondata-upstox'

# Change the current working directory to the script directory
os.chdir(script_directory)

# Define the scripts to run
scripts = ['nifty1.py', 'sensex.py']

# Create threads for each script
threads = []
for script in scripts:
    thread = threading.Thread(target=run_script, args=(script,))
    threads.append(thread)
    thread.start()

# Wait for all threads to complete
for thread in threads:
    thread.join()

print("Both scripts have finished running.")
