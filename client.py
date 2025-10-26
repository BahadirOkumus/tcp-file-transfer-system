import socket
import threading
import os
import sys

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class Connection:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._buffer = bytearray()
        self.sock.settimeout(None)

    def recv_line(self) -> str:
        while True:
            nl_index = self._buffer.find(b"\n")
            if nl_index != -1:
                line = self._buffer[:nl_index + 1]
                del self._buffer[:nl_index + 1]
                return line.decode("utf-8", errors="replace")
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Sunucu bağlantısı kapandı")
            self._buffer.extend(chunk)

    def recv_exact(self, n: int) -> bytes:
        data = bytearray()
        if self._buffer:
            take = min(n, len(self._buffer))
            data.extend(self._buffer[:take])
            del self._buffer[:take]
            n -= take
        while n > 0:
            chunk = self.sock.recv(min(4096, n))
            if not chunk:
                raise ConnectionError("Sunucu bağlantısı kapandı")
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

class TCPClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn = None
        self._running = True

    def start(self):
        self.sock.connect((self.host, self.port))
        self.conn = Connection(self.sock)
        print(f"[CLIENT] Sunucuya bağlandı: {self.host}:{self.port}")
        t = threading.Thread(target=self._receiver_loop, daemon=True)
        t.start()
        self._sender_loop()

    def _receiver_loop(self):
        try:
            while self._running:
                header = self.conn.recv_line().rstrip("\n")
                if header.startswith("MSG|"):
                    _, msg = header.split("|", 1)
                    print(f"\n[Mesaj] {msg}")
                elif header.startswith("FILE|"):
                    parts = header.split("|")
                    if len(parts) != 3:
                        print(f"[UYARI] Geçersiz FILE başlığı: {header}")
                        continue
                    _, filename, size_str = parts
                    try:
                        size = int(size_str)
                    except ValueError:
                        print(f"[UYARI] Geçersiz boyut: {size_str}")
                        continue
                    data = self.conn.recv_exact(size)
                    save_path = self._unique_save_path(filename)
                    with open(save_path, "wb") as f:
                        f.write(data)
                    print(f"\n[Dosya] Alındı ve kaydedildi: {save_path} ({size} bayt)")
                else:
                    print(f"[UYARI] Bilinmeyen başlık: {header}")
        except (ConnectionError, OSError):
            print("\n[CLIENT] Sunucu bağlantısı kapandı. Alıcı döngüsü sonlanıyor.")
        finally:
            self._running = False

    def _sender_loop(self):
        try:
            while self._running:
                print("\nBir işlem seçin: [m]esaj, [f]dosya, [q]çıkış")
                choice = input("> ").strip().lower()
                if choice == "q":
                    self._running = False
                    break
                elif choice == "m":
                    text = input("Mesaj: ")
                    text = text.replace("\n", " ")  # Çok satırlı girişleri sadeleştir
                    self.conn.sendall(f"MSG|{text}\n".encode("utf-8"))
                elif choice == "f":
                    path = input("Dosya yolu: ").strip().strip('"')
                    if not os.path.isfile(path):
                        print("[HATA] Dosya bulunamadı.")
                        continue
                    filename = os.path.basename(path)
                    with open(path, "rb") as f:
                        data = f.read()
                    header = f"FILE|{filename}|{len(data)}\n".encode("utf-8")
                    try:
                        self.conn.sendall(header)
                        self.conn.sendall(data)
                        print(f"[CLIENT] Gönderildi: {filename} ({len(data)} bayt)")
                    except Exception as e:
                        print(f"[HATA] Gönderim hatası: {e}")
                else:
                    print("[UYARI] Geçersiz seçim.")
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            print("[CLIENT] Çıkıldı.")

    def _unique_save_path(self, filename: str) -> str:
        base = os.path.basename(filename)
        root, ext = os.path.splitext(base)
        candidate = os.path.join(DOWNLOAD_DIR, base)
        idx = 1
        while os.path.exists(candidate):
            candidate = os.path.join(DOWNLOAD_DIR, f"{root}_{idx}{ext}")
            idx += 1
        return candidate

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Kullanım: python client.py <sunucu_ip> <port>")
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2])
    client = TCPClient(host, port)
    client.start()