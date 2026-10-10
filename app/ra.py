#!/usr/bin/env python3
# Runs on the handheld: RetroArch network-command client (UDP 55355, needs network_cmd_enable = "true").
# Usage: ra.py CMD...            e.g. ra.py VERSION | ra.py GET_STATUS | ra.py READ_CORE_RAM 0 128
# As a module: RA().cmd("FRAMEADVANCE"), RA().ram(0x80, 128) -> bytes
import socket, sys

class RA:
    def __init__(self, host="127.0.0.1", port=55355, timeout=1.0):
        self.addr = (host, port); self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); self.s.settimeout(timeout)

    def cmd(self, line, reply=True):
        self.s.sendto(line.encode(), self.addr)
        if not reply: return None
        try: return self.s.recv(65536).decode(errors="replace").strip()
        except socket.timeout: return None

    def ram(self, addr, n, verb="READ_CORE_MEMORY"):
        """bytes at addr..addr+n via READ_CORE_MEMORY (memory map) or READ_CORE_RAM (achievement map); None on error."""
        r = self.cmd("%s %x %d" % (verb, addr, n))
        if not r: return None
        parts = r.split()
        if len(parts) < 3 or parts[2] == "-1": return None
        return bytes(int(x, 16) for x in parts[2:])

if __name__ == "__main__":
    print(RA().cmd(" ".join(sys.argv[1:])))
