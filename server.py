import socket
import threading
import os
import sys
from typing import List, Tuple

# Basit ve sağlam bir TCP protokolü:
# - Mesajlar: "MSG|<metin>\n" (UTF-8)
# - Dosyalar: "FILE|<dosya_adi>|<bayt_sayisi>\n" ardından baytların kendisi
# Bu sayede ikili dosyalar (.jpg, .pdf vb.) güvenli şekilde iletilebilir.

RECV_DIR = os.path.join(os.path.dirname(__file__), "received")
os.makedirs(RECV_DIR, exist_ok=True)

class Connection:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int]):
        self.sock = sock
        self.addr = addr
        self._buffer = bytearray()
        self.sock.settimeout(None)

    def recv_line(self) -> str:
        """\n        Yeni satır (\n) ile biten başlık satırını okur. UTF-8 döner.\n        TCP parçalanabileceği için iç tamponu kullanır.\n        """
        while True:
            nl_index = self._buffer.find(b"\n")
            if nl_index != -1:
                line = self._buffer[:nl_index + 1]
                del self._buffer[:nl_index + 1]
                return line.decode("utf-8", errors="replace")
            chunk = self.sock.recv(4096)
            if not chunk:
                # Bağlantı kapandı
                raise ConnectionError("Socket closed while waiting for line")
            self._buffer.extend(chunk)

    def recv_exact(self, n: int) -> bytes:
        """Tam olarak n baytı okur (tamponu da kullanır)."""
        # Önce tampondan al
        data = bytearray()
        if self._buffer:
            take = min(n, len(self._buffer))
            data.extend(self._buffer[:take])
            del self._buffer[:take]
            n -= take
        while n > 0:
            chunk = self.sock.recv(min(4096, n))
            if not chunk:
                raise ConnectionError("Socket closed while receiving payload")
            data.extend(chunk)
            n -= len(chunk)
        return bytes(data)

    def sendall(self, b: bytes):
        self.sock.sendall(b)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

class TCPServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 65432):
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: List[Connection] = []
        self.clients_lock = threading.Lock()

    def start(self):
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(100)
        print(f"[SERVER] Dinleniyor: {self.host}:{self.port}")
        try:
            while True:
                client_sock, addr = self.server_sock.accept()
                conn = Connection(client_sock, addr)
                with self.clients_lock:
                    self.clients.append(conn)
                print(f"[SERVER] İstemci bağlandı: {addr}")
                t = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                t.start()
        except KeyboardInterrupt:
            print("\n[SERVER] Kapatılıyor...")
        finally:
            self.shutdown()

    def broadcast(self, sender: Connection, header_line: str, payload: bytes = b""):
        """Diğer istemcilere gönderir. Header ve (varsa) payload'u aynen iletir."""
        with self.clients_lock:
            targets = [c for c in self.clients if c is not sender]
        for c in targets:
            try:
                c.sendall(header_line.encode("utf-8"))
                if payload:
                    c.sendall(payload)
            except Exception as e:
                print(f"[SERVER] Yayın sırasında hata {c.addr}: {e}. İstemci kaldırılıyor.")
                self.remove_client(c)

    def remove_client(self, conn: Connection):
        with self.clients_lock:
            if conn in self.clients:
                self.clients.remove(conn)
        conn.close()

    def handle_client(self, conn: Connection):
        try:
            while True:
                header = conn.recv_line().rstrip("\n")
                if header.startswith("MSG|"):
                    # MSG|<text>
                    _, msg = header.split("|", 1)
                    print(f"[MSG] {conn.addr}: {msg}")
                    # Diğer istemcilere aktar
                    self.broadcast(conn, f"MSG|{msg}\n")
                elif header.startswith("FILE|"):
                    # FILE|<filename>|<size>
                    parts = header.split("|")
                    if len(parts) != 3:
                        print(f"[WARN] Geçersiz FILE başlığı: {header}")
                        continue
                    _, filename, size_str = parts
                    try:
                        size = int(size_str)
                    except ValueError:
                        print(f"[WARN] Geçersiz boyut: {size_str}")
                        continue
                    data = conn.recv_exact(size)
                    save_path = self._unique_save_path(filename)
                    with open(save_path, "wb") as f:
                        f.write(data)
                    print(f"[FILE] {conn.addr} -> kaydedildi: {save_path} ({size} bayt)")
                    # Diğer istemcilere aynen ilet
                    self.broadcast(conn, f"FILE|{filename}|{size}\n", data)
                else:
                    # Bilinmeyen başlık veya protokol
                    print(f"[WARN] Bilinmeyen başlık: {header}")
        except (ConnectionError, OSError):
            print(f"[SERVER] Bağlantı kapandı: {conn.addr}")
        finally:
            self.remove_client(conn)

    def _unique_save_path(self, filename: str) -> str:
        # Aynı dosya adı varsa çakışmayı önlemek için numaralandır
        base = os.path.basename(filename)
        root, ext = os.path.splitext(base)
        candidate = os.path.join(RECV_DIR, base)
        idx = 1
        while os.path.exists(candidate):
            candidate = os.path.join(RECV_DIR, f"{root}_{idx}{ext}")
            idx += 1
        return candidate

    def shutdown(self):
        with self.clients_lock:
            for c in list(self.clients):
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()
        try:
            self.server_sock.close()
        except Exception:
            pass
        print("[SERVER] Kapandı.")

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 65432
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])
    srv = TCPServer(host, port)
    srv.start()