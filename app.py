# SmartPick 1~3등 자동제외 로또 추천 웹앱 (최신 통합버전)
# 구글 애드센스/SEO/고급UI/사용자 필터 모두 반영

from flask import Flask, render_template, request
import random, json, os

app = Flask(__name__)

# ===== [1] 1~3등 당첨번호 파일 경로 설정 =====
BASE_DIR = os.path.dirname(__file__)
WINNING1_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_full.json')
WINNING2_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank2.json')
WINNING3_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank3.json')

# ===== [2] 파일에서 각 등수별 당첨번호를 읽어 set으로 합치기 =====
def load_rank(path, key, length=6):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            # 숫자 정렬/중복방지
            return [tuple(sorted(row[:length])) for row in data.get(key, [])]
    except Exception as e:
        print(f"{path} 파일 읽기 에러:", e)
        return []

rank1 = load_rank(WINNING1_PATH, 'rank1', 6)
rank2 = load_rank(WINNING2_PATH, 'rank2', 6)
rank3 = load_rank(WINNING3_PATH, 'rank3', 5)  # 3등은 5개짜리 조합
ALL_WINNING = set(rank1 + rank2 + rank3)

# ===== [3] 추천번호 생성 (1~3등, 사용자 입력 제외/고정 모두 반영) =====
def generate_numbers(user_exclude=None, user_include=None):
    tries = 0
    while True:
        nums = set(random.sample(range(1, 46), 6))
        if user_include and not set(user_include).issubset(nums):
            continue
        if user_exclude and nums.intersection(set(user_exclude)):
            continue
        nums_tuple = tuple(sorted(nums))
        if nums_tuple not in ALL_WINNING:
            return sorted(nums)
        tries += 1
        if tries > 10000:  # 무한루프 방지
            return None

# ===== [4] Flask 라우팅 (홈/추천) =====
@app.route("/", methods=["GET", "POST"])
def home():
    numbers = None
    exclude = ""
    include = ""
    if request.method == "POST":
        exclude = request.form.get("exclude", "")
        include = request.form.get("include", "")
        exclude_list = [int(n) for n in exclude.replace(" ", "").split(",") if n.isdigit()]
        include_list = [int(n) for n in include.replace(" ", "").split(",") if n.isdigit()]
        numbers = generate_numbers(user_exclude=exclude_list, user_include=include_list)
    return render_template("index.html", numbers=numbers, exclude=exclude, include=include)

if __name__ == '__main__':
    app.run(debug=True)
