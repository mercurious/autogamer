#!/usr/bin/env python3
# Runs on the handheld: a virtual RetroPad for player 1 through RetroArch's network remote (UDP 55400,
# network_remote_enable + network_remote_enable_user_p1). A pressed button stays pressed until released.
# Usage: pad.py BUTTON [SECONDS]   (tap: press, hold SECONDS (default 0.15), release)
import socket, struct, sys, time
IDS = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6, "right": 7,
       "a": 8, "x": 9, "l": 10, "r": 11, "l2": 12, "r2": 13, "l3": 14, "r3": 15}
JOYPAD = 1

class Pad:
    def __init__(self, host="127.0.0.1", port=55400, user=0):
        self.addr = (host, port + user); self.user = user
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); self.held = set()

    def set(self, button, on):
        # struct remote_message { int port; int device; int index; int id; uint16_t state; } = 20 bytes with padding
        self.s.sendto(struct.pack("<iiiiH2x", self.user, JOYPAD, 0, IDS[button], 1 if on else 0), self.addr)
        (self.held.add if on else self.held.discard)(button)

    def hold(self, buttons):
        """make exactly these buttons pressed"""
        for b in list(self.held - set(buttons)): self.set(b, False)
        for b in set(buttons) - self.held: self.set(b, True)

    def nudge(self, buttons, order=("a", "left", "right", "down", "up", "b")):
        """one step toward exactly these buttons pressed: at most one message, the first difference in order (then
        any other). RetroArch's network remote reads one message per user per frame and queues the rest, so a pad
        that changes more than once a frame falls further and further behind; call this once a frame."""
        want = set(buttons)
        for b in list(order) + sorted(IDS):
            if (b in want) != (b in self.held): self.set(b, b in want); return b
        return None

    def tap(self, button, secs=0.15):
        self.set(button, True); time.sleep(secs); self.set(button, False)

    def release_all(self):
        for b in IDS: self.set(b, False)

if __name__ == "__main__":
    Pad().tap(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.15)
