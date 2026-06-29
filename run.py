import socket
from dotenv import load_dotenv
load_dotenv()
from app import create_app

app = create_app()

if __name__ == '__main__':
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  Local:   http://127.0.0.1:5000")
    print(f"  Mobile:  http://{local_ip}:5000  (same Wi-Fi)\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
    