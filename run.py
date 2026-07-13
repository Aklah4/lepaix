import socket
from dotenv import load_dotenv
load_dotenv()
from app import create_app

app = create_app()

if __name__ == '__main__':
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  Local:   http://127.0.0.1:5000")
    print(f"  Mobile:  http://{local_ip}:5000  (same Wi-Fi)\n")
    # use_reloader=False: Werkzeug's auto-reloader crashes on startup on
    # Windows + Python 3.14 with WinError 10038 (socket handoff bug in the
    # reloader's subprocess restart). Debug mode/error pages still work;
    # restart manually after code changes instead of relying on auto-reload.
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000, use_reloader=False)
    