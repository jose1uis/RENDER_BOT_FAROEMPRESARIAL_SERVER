from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os

app = Flask(__name__)
CORS(app)

openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/chat", methods=["POST"])
def chat():

    data = request.json
    mensaje = data["mensaje"]

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role":"system",
                "content":"Eres el asesor empresarial de FARO Empresarial SAS."
            },
            {
                "role":"user",
                "content":mensaje
            }
        ]
    )

    return jsonify({
        "respuesta":response.choices[0].message.content
    })