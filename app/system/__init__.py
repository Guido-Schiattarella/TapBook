"""Operating-system specific parts, outside the MVC pattern.

  tls.py        HTTPS certificates (local CA and server certificate)
  network.py    the computer's addresses on the local network
  updates.py    check for a newer Release on GitHub
  firewall/     server port in the firewall, open only while the server is running
                (Linux: linux_helper.py with sudo; Windows: windows_helper.py with UAC)
"""
