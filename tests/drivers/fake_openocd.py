"""Stand-in for the openocd program in driver tests.

Prints its arguments. When a -c command contains "fail" it ends with exit code 1; when
one contains "slow" it sleeps for 10 seconds first.
"""

import sys
import time

args = sys.argv[1:]
commands = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-c"]
joined = " ".join(commands)
print("Open On-Chip Debugger (fake)", flush=True)
print("args: " + " | ".join(args), flush=True)
if "slow" in joined:
    time.sleep(10)
if "fail" in joined:
    print("Error: simulated failure", file=sys.stderr, flush=True)
    sys.exit(1)
print("** Programming Finished **" if "program" in joined else "done", flush=True)
