from flask import Flask, render_template, redirect, url_for
import random
import json
import os

app = Flask(__name__)

# 1등 당첨번호 JSON 경로 설정
WINNING_PATH = os.path.join(os.path.dirname(__file__), 'static', 'winning_numbers_full.json')

# JSON 파일 불러오기 (처음 한 번만)
def load_winning_numbers():
    try:
        with open(WINNING_PATH, encoding='utf-8') as f:
            data = json.load(f)
            return [tuple(sorted(nums)) for nums in data.get("rank1", [])]
    except Exception as e:
        print("1등 번호 로딩 실패:", e)
        return []

WINNING_NUMBERS = load_winning_numbers()

# 1등 조합과 중복되지 않는 로또 번호 생성
def generate_unique_lotto():
    while True:
        nums = sorted(random.sample(range(1, 46), 6))
        if tuple(nums) not in WINNING_NUMBERS:
            return nums

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate')
def generate():
    lotto = generate_unique_lotto()
    return render_template('generate.html', lotto=lotto)

if __name__ == "__main__":
    app.run(debug=True)
