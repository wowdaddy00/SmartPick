from flask import Flask, render_template, request
import random, json, os

app = Flask(__name__)

# 1~3등 당첨 번호 불러오기
WINNING_PATH = os.path.join(app.root_path, 'static', 'winning_numbers_full.json')
try:
    with open(WINNING_PATH, encoding='utf-8') as f:
        WINNING = json.load(f)
    # rank1, rank2, rank3가 모두 있으면 모두 읽어오기
    rank_lists = []
    for k in ["rank1", "rank2", "rank3"]:
        if k in WINNING:
            rank_lists.extend([tuple(sorted(row)) for row in WINNING[k]])
    EXCLUDE_TUPLES = set(rank_lists)
except Exception as e:
    EXCLUDE_TUPLES = set()

# 번호 추천 (사용자 제외/고정 번호 모두 반영)
def generate_numbers(user_exclude=None, user_include=None):
    tries = 0
    while True:
        nums = set(random.sample(range(1, 46), 6))
        # 고정번호(필수포함) 체크
        if user_include and not set(user_include).issubset(nums):
            continue
        # 제외번호 체크
        if user_exclude and nums.intersection(set(user_exclude)):
            continue
        nums = sorted(nums)
        if tuple(nums) not in EXCLUDE_TUPLES:
            return nums
        tries += 1
        if tries > 10000:  # 무한루프 방지
            return None

@app.route("/", methods=["GET", "POST"])
def home():
    numbers = None
    exclude = ""
    include = ""
    if request.method == "POST":
        exclude = request.form.get("exclude", "")
        include = request.form.get("include", "")
        # 입력값 처리(쉼표, 공백 모두 허용)
        exclude_list = [int(n) for n in exclude.replace(" ", "").split(",") if n.isdigit()]
        include_list = [int(n) for n in include.replace(" ", "").split(",") if n.isdigit()]
        numbers = generate_numbers(user_exclude=exclude_list, user_include=include_list)
    return render_template("index.html", numbers=numbers, exclude=exclude, include=include)

if __name__ == '__main__':
    app.run(debug=True)
