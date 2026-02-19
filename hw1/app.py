from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "message": "user info service",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
