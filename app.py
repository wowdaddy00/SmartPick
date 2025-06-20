import os, json, random
from flask import Flask, render_template, request
from collections import Counter


app = Flask(__name__)

import datetime

def log_event(event, detail=None):
    log = {
        "dt": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "event": event,
        "detail": detail or {}
    }
    logfile = "admin_log.json"
    try:
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    except Exception as e:
        print("로그 기록 오류:", e)

# [1] 1~3등 당첨번호 DB 파일 경로
BASE_DIR = os.path.dirname(__file__)
WINNING1_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_full.json')
WINNING2_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank2.json')
WINNING3_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank3.json')

# [2] 각 DB 파일 불러오기
def load_rank(path, key, length=6):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return [tuple(sorted(row[:length])) for row in data.get(key, [])]
    except Exception as e:
        print(f"{path} 파일 읽기 에러:", e)
        return []

rank1 = load_rank(WINNING1_PATH, 'rank1', 6)
rank2 = load_rank(WINNING2_PATH, 'rank2', 6)
rank3 = load_rank(WINNING3_PATH, 'rank3', 5)
ALL_WINNING = {
    "1": set(rank1),
    "2": set(rank2),
    "3": set(rank3)
}

# [3] 최근 N회 많이 나온 번호
def get_hot_numbers(n=5):
    all_nums = []
    for row in rank1[-n:]:
        all_nums.extend(row)
    freq = {}
    for num in all_nums:
        freq[num] = freq.get(num, 0) + 1
    sorted_nums = [k for k, v in sorted(freq.items(), key=lambda x: -x[1])]
    return set(sorted_nums)

# [4] 연속번호 판단
def has_consecutive(numbers, seq_len=2):
    nums = sorted(numbers)
    count = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i-1]+1:
            count += 1
            if count >= seq_len:
                return True
        else:
            count = 1
    return False

# [5] 추천번호 생성(모든 필터 반영)
def generate_numbers(
    exclude_ranks=[],
    exclude_hot_n=None,
    exclude_consecutive=None,
    user_exclude=None,
    user_include=None,
    count=1
):
    results = []
    tries = 0
    exclude_db = set()
    for r in exclude_ranks:
        exclude_db.update(ALL_WINNING.get(r, set()))
    hot_numbers = get_hot_numbers(exclude_hot_n) if exclude_hot_n else set()
    # 추천 번호 세트 생성
    while len(results) < count:
        nums = set(random.sample(range(1, 46), 6))
        # 고정번호(필수 포함)
        if user_include and not set(user_include).issubset(nums):
            continue
        # 제외번호(직접입력)
        if user_exclude and nums.intersection(set(user_exclude)):
            continue
        # 등수별 당첨조합 제외
        if exclude_db and tuple(sorted(nums)) in exclude_db:
            continue
        # 최근 N회 핫번호 제외
        if exclude_hot_n and nums.intersection(hot_numbers):
            continue
        # 연속번호 필터
        if exclude_consecutive and has_consecutive(nums, exclude_consecutive):
            continue
        # 중복 세트 방지
        if sorted(nums) in results:
            continue
        results.append(sorted(nums))
        tries += 1
        if tries > 30000:
            break
    return results

# [6] 입력 값 유효성 검증 함수
def parse_int_list(text):
    return [int(n) for n in str(text).replace(" ", "").split(",") if str(n).isdigit()]

# [7] 무료 추천 (조건 없이 1세트)
@app.route("/", methods=["GET", "POST"])
def free():
    log_event("visit", {"page": "index"})
    numbers = None
    error = ""
    if request.method == "POST":
        numbers = generate_numbers(count=1)
        log_event("recommend", {
            "page": "index",
            "numbers": numbers,
            "user_ip": request.remote_addr
        })
        if not numbers:
            error = "추천 가능한 번호가 없습니다."
    return render_template("index.html", numbers=numbers, error=error)

# [8] 조건 추천 (필터+추천개수 등 선택)
@app.route("/filter", methods=["GET", "POST"])
def filter_page():
    log_event("visit", {"page": "filter"}) 
    numbers = []
    form = {}
    error = ""
    if request.method == "POST":
        try:
            exclude_ranks = request.form.getlist("exclude_ranks")
            exclude_hot_n = int(request.form.get("exclude_hot_n") or 0) or None
            exclude_consecutive = int(request.form.get("exclude_consecutive") or 0) or None
            user_exclude = parse_int_list(request.form.get("user_exclude", ""))
            user_include = parse_int_list(request.form.get("user_include", ""))
            count = int(request.form.get("count") or 5)
            # **고정번호가 2개 이상일 때 에러 처리**
            if len(user_include) > 1:
                error = "고정할 번호는 1개만 입력할 수 있습니다."
                numbers = []
            else:
                numbers = generate_numbers(
                    exclude_ranks=exclude_ranks,
                    exclude_hot_n=exclude_hot_n,
                    exclude_consecutive=exclude_consecutive,
                    user_exclude=user_exclude,
                    user_include=user_include,
                    count=count
                )
                form = dict(request.form)
                if not numbers and not error:
                    error = "조건에 맞는 추천번호가 없습니다. (필터를 줄여 다시 시도해주세요)"
        except Exception as e:
            error = f"입력값 오류: {e}"
    return render_template("filter.html", numbers=numbers, error=error, form=form)
    
@app.route('/about')
def about():
    log_event("visit", {"page": "about"})
    return render_template('about.html')

@app.route('/privacy')
def privacy():
    log_event("visit", {"page": "privacy"})
    return render_template('privacy.html')

@app.route('/disclaimer')
def disclaimer():
    log_event("visit", {"page": "disclaimer"})
    return render_template('disclaimer.html')

@app.route('/contact')
def contact():
    log_event("visit", {"page": "contact"})
    return render_template('contact.html')

@app.route('/stats')
def stats():
    log_event("visit", {"page": "stats"})
    recent_n = 10  # 최근 10주 기준 (20, 52 등으로 변경 가능)
    numbers = []
    for row in rank1[-recent_n:]:
        numbers.extend(row)
    freq = dict(Counter(numbers))
    for n in range(1, 46):
        freq.setdefault(n, 0)
    freq = dict(sorted(freq.items()))
    return render_template('stats.html', freq_json=freq, recent_n=recent_n)

@app.route('/admin')
def admin():
    pw = request.args.get("pw","")
    if pw != "1234":   # 실운영시 더 안전하게!
        return "관리자 인증 필요(pw=1234)", 403
    logs = []
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except:
        pass
    # 예시 통계 집계
    total_visits = sum(1 for log in logs if log["event"]=="visit")
    total_recs = sum(1 for log in logs if log["event"]=="recommend")
    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs)


if __name__ == '__main__':
    app.run(debug=True)
