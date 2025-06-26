import os, json, random
from flask import Flask, render_template, request
from collections import Counter
import datetime
import requests
import itertools

app = Flask(__name__)

# Function to log events for administration
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

# Function to get the latest lottery round number
def get_latest_round():
    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    for drw in range(1200, 1000, -1): # Search from a high number down to 1001 for recent rounds
        resp = requests.get(url + str(drw))
        data = resp.json()
        if data.get('returnValue') == 'success' and all(isinstance(data.get(f'drwtNo{i}'), int) for i in range(1, 7)):
            return drw
    return None

# Function to fetch latest lotto numbers with bonus number
def fetch_latest_lotto_with_bonus():
    latest = get_latest_round()
    if latest is None:
        return None, None, None

    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    resp = requests.get(url + str(latest))
    data = resp.json()
    
    required_keys = [f'drwtNo{i}' for i in range(1, 7)] + ['bnusNo']
    if not all(key in data and isinstance(data[key], int) for key in required_keys):
        return None, None, None

    nums = [data[f'drwtNo{i}'] for i in range(1, 7)]
    bonus = data['bnusNo']
    return latest, nums, bonus

# Function to generate combinations for 2nd and 3rd rank numbers
def make_rank2_3(nums, bonus):
    combis = list(itertools.combinations(nums, 5))
    rank2 = []
    rank3 = []
    for c in combis:
        if bonus in c:
            rank2.append(tuple(sorted(c)))
        else:
            rank3.append(tuple(sorted(c)))
    return rank2, rank3

# Paths to the JSON files storing winning numbers data
BASE_DIR = os.path.dirname(__file__)
WINNING1_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_full.json')
WINNING2_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank2.json')
WINNING3_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank3.json')

# Function to load winning rank data from JSON files
def load_rank(path, key, length=6):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return [tuple(sorted(row[:length])) for row in data.get(key, [])]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"{path} 파일 읽기/디코딩 에러 (새 파일 생성):", e)
        return []
    except Exception as e:
        print(f"{path} 파일 읽기 에러:", e)
        return []

# Load all historical winning numbers into sets for quick lookup
# These will be reloaded in update_winning after file changes
rank1 = load_rank(WINNING1_PATH, 'rank1', 6)
rank2 = load_rank(WINNING2_PATH, 'rank2', 6)
rank3 = load_rank(WINNING3_PATH, 'rank3', 5)
ALL_WINNING = {
    "1": set(rank1),
    "2": set(rank2),
    "3": set(rank3)
}

# Function to get frequently appearing numbers from recent N draws
def get_hot_numbers(n=5):
    all_nums = []
    for row in rank1[-n:]:
        all_nums.extend(row)
    
    freq = {}
    for num in all_nums:
        freq[num] = freq.get(num, 0) + 1
    
    sorted_nums = [k for k, v in sorted(freq.items(), key=lambda x: -x[1])]
    return set(sorted_nums)

# Function to check if a set of numbers contains a consecutive sequence
def has_consecutive(numbers, seq_len=2):
    nums = sorted(list(numbers))
    count = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i-1] + 1:
            count += 1
            if count >= seq_len:
                return True
        else:
            count = 1
    return False

# Function to generate lottery numbers based on various filters
def generate_numbers(
    exclude_ranks=[],
    exclude_hot_n=None, # This is now for 'filter' logic, not hotpick
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
    
    hot_numbers_to_exclude = get_hot_numbers(exclude_hot_n) if exclude_hot_n else set()
    
    while len(results) < count:
        nums = set(random.sample(range(1, 46), 6))
        
        # 1. User required numbers (user_include)
        if user_include and not set(user_include).issubset(nums):
            tries += 1
            if tries > 30000: break
            continue
        
        # 2. User excluded numbers (user_exclude)
        if user_exclude and nums.intersection(set(user_exclude)):
            tries += 1
            if tries > 30000: break
            continue
        
        # 3. Exclude past winning combinations (by rank)
        if exclude_db:
            if tuple(sorted(nums)) in ALL_WINNING.get("1", set()):
                tries += 1
                if tries > 30000: break
                continue
            if tuple(sorted(nums)) in ALL_WINNING.get("2", set()):
                tries += 1
                if tries > 30000: break
                continue
            is_rank3_match = False
            for combo in itertools.combinations(nums, 5):
                if tuple(sorted(combo)) in ALL_WINNING.get("3", set()):
                    is_rank3_match = True
                    break
            if is_rank3_match:
                tries += 1
                if tries > 30000: break
                continue

        # 4. Exclude recent hot numbers (when used as a filter, NOT a generation method)
        if exclude_hot_n and nums.intersection(hot_numbers_to_exclude):
            tries += 1
            if tries > 30000: break
            continue
        
        # 5. Exclude consecutive numbers if specified
        if exclude_consecutive and has_consecutive(nums, exclude_consecutive):
            tries += 1
            if tries > 30000: break
            continue
        
        # 6. Prevent duplicate sets in the results
        if sorted(list(nums)) in results:
            tries += 1
            if tries > 30000: break
            continue
            
        results.append(sorted(list(nums)))
        # Do NOT increment tries for successful generation, only for rejected tries
        # This allows it to generate 'count' numbers without hitting max_tries too soon if filters are strict

        if tries > 300000: # Increase safety break for strict filters
            print("경고: 필터 조건이 너무 엄격하여 번호 생성 시도 횟수 초과. 일부 결과가 누락될 수 있습니다.")
            break
    return results

# Function to parse a comma-separated string of integers into a list
def parse_int_list(text):
    if not text:
        return []
    return [int(n) for n in str(text).replace(" ", "").split(",") if str(n).isdigit()]

# Route for the free recommendation page (root URL)
@app.route("/", methods=["GET", "POST"])
def free():
    log_event("visit", {"page": "index"})
    numbers = None
    error = ""
    
    total_recs = 0
    today_recs = 0
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            for line in f:
                if '"event": "recommend"' in line:
                    total_recs += 1
                    if today in line:
                        today_recs += 1
    except:
        pass
        
    if request.method == "POST":
        # 'SmartPick 프리미엄 번호 추천받기' 버튼 클릭 시
        # 기본적으로 1,2,3등 당첨 번호 제외 필터를 적용
        numbers = generate_numbers(count=1, exclude_ranks=['1', '2', '3'])
        log_event("recommend", {
            "page": "index_premium_quick",
            "numbers": numbers,
            "user_ip": request.remote_addr
        })
        if not numbers:
            error = "추천 가능한 프리미엄 번호가 없습니다. (필터를 줄이거나 다시 시도해주세요)"
            
    return render_template(
        "index.html",
        numbers=numbers,
        error=error,
        total_recs=total_recs,
        today_recs=today_recs
    )

# New Route for choosing recommendation type
@app.route('/choose_recommendation')
def choose_recommendation():
    log_event("visit", {"page": "choose_recommendation"})
    return render_template('choose_recommendation.html')

# Route for the detailed filtered recommendation page (formerly /filter)
@app.route("/filter", methods=["GET", "POST"])
def detailed_filter_page():
    log_event("visit", {"page": "detailed_filter"})
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
                
                log_event("recommend", {
                    "page": "detailed_filter",
                    "numbers": numbers,
                    "user_ip": request.remote_addr,
                    "condition": dict(request.form)
                })
        except Exception as e:
            error = f"입력값 오류: {e}"
            
    return render_template("filter.html", numbers=numbers, error=error, form=form)

# New Route for Hot Pick recommendation page
@app.route("/hotpick", methods=["GET", "POST"])
def hotpick_page():
    log_event("visit", {"page": "hotpick"})
    numbers = []
    form = {}
    error = ""

    if request.method == "POST":
        try:
            hot_pick_n = int(request.form.get("hot_pick_n") or 0) or None
            count = int(request.form.get("count") or 1)
            
            if hot_pick_n:
                recent_nums = []
                for row in rank1[-hot_pick_n:]:
                    recent_nums.extend(row)
                
                counts = Counter(recent_nums)
                
                generated_numbers = []
                # Fix for problem 6: Ensure 'count' sets are generated for hotpick
                for _ in range(count):
                    top6 = [num for num, cnt in counts.most_common(6)]
                    if len(top6) < 6:
                        top6 += random.sample([n for n in range(1,46) if n not in top6], 6 - len(top6))
                    random.shuffle(top6)
                    generated_numbers.append(sorted(top6))
                
                numbers = generated_numbers
                form = dict(request.form)
                
                log_event("recommend", {
                    "page": "hotpick_recommendation",
                    "numbers": numbers,
                    "user_ip": request.remote_addr,
                    "condition": dict(request.form)
                })
            else:
                error = "최근 많이 나온 번호 추천 주기를 선택해주세요."
            
        except Exception as e:
            error = f"입력값 오류: {e}"
    
    return render_template("hotpick.html", numbers=numbers, error=error, form=form)


# Route for the About page
@app.route('/about')
def about():
    log_event("visit", {"page": "about"})
    return render_template('about.html')

# Route for the Privacy Policy page
@app.route('/privacy')
def privacy():
    log_event("visit", {"page": "privacy"})
    return render_template('privacy.html')

# Route for the Disclaimer page
@app.route('/disclaimer')
def disclaimer():
    log_event("visit", {"page": "disclaimer"})
    return render_template('disclaimer.html')

# Route for the Contact page
@app.route('/contact')
def contact():
    log_event("visit", {"page": "contact"})
    return render_template('contact.html')

# Route for the Statistics page
@app.route('/stats')
def stats():
    log_event("visit", {"page": "stats"})
    recent_n = 10 
    numbers = []
    for row in rank1[-recent_n:]:
        numbers.extend(row)
    
    freq = dict(Counter(numbers))
    for n in range(1, 46):
        freq.setdefault(n, 0)
    freq = dict(sorted(freq.items()))
    
    return render_template('stats.html', freq_json=freq, recent_n=recent_n)

# Route for the Admin page (requires password for access)
@app.route('/admin')
def admin():
    pw = request.args.get("pw", "")
    if pw != "1234":
        return "관리자 인증 필요(pw=1234)", 403
    
    logs = []
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except:
        pass
    
    total_visits = sum(1 for log in logs if log["event"]=="visit")
    total_recs = sum(1 for log in logs if log["event"]=="recommend")
    
    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs)

# Route to update winning numbers (admin functionality)
@app.route("/update_winning", methods=["POST"])
def update_winning():
    pw = request.form.get("pw")
    
    if pw != "1234":
        logs = []
        try:
            with open("admin_log.json", encoding="utf-8") as f:
                logs = [json.loads(line) for line in f if line.strip()]
        except:
            pass
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg="비밀번호가 틀렸습니다.")

    latest, nums, bonus = fetch_latest_lotto_with_bonus()
    
    if latest is None or nums is None or bonus is None:
        msg = "아직 최신 회차 당첨번호가 공개되지 않았습니다.<br>잠시 후 다시 시도해 주세요."
        logs = []
        try:
            with open("admin_log.json", encoding="utf-8") as f:
                logs = [json.loads(line) for line in f if line.strip()]
        except:
            pass
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg=msg)
        
    # --- Update Rank 1 Data ---
    try:
        os.makedirs(os.path.dirname(WINNING1_PATH), exist_ok=True)
        with open(WINNING1_PATH, encoding="utf-8") as f:
            db_rank1 = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_rank1 = {"rank1": []}
    
    if nums not in db_rank1["rank1"]:
        db_rank1["rank1"].append(nums)
        with open(WINNING1_PATH, "w", encoding="utf-8") as f:
            json.dump(db_rank1, f, ensure_ascii=False, indent=2)
        msg_rank1 = f"{latest}회차 1등 번호 {nums} 저장 완료!"
    else:
        msg_rank1 = f"1등 번호 (회차 {latest})는 이미 최신으로 반영되어 있습니다."

    # --- Update Rank 2 & 3 Data ---
    rank2_new, rank3_new = make_rank2_3(nums, bonus)

    # Update Rank 2
    try:
        os.makedirs(os.path.dirname(WINNING2_PATH), exist_ok=True)
        with open(WINNING2_PATH, encoding="utf-8") as f:
            db_rank2 = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_rank2 = {"rank2": []}
    
    for r2_combo in rank2_new:
        if list(r2_combo) not in db_rank2["rank2"]:
            db_rank2["rank2"].append(list(r2_combo))
    with open(WINNING2_PATH, "w", encoding="utf-8") as f:
        json.dump(db_rank2, f, ensure_ascii=False, indent=2)
    msg_rank2 = "2등 조합 업데이트 완료."


    # Update Rank 3
    try:
        os.makedirs(os.path.dirname(WINNING3_PATH), exist_ok=True)
        with open(WINNING3_PATH, encoding="utf-8") as f:
            db_rank3 = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db_rank3 = {"rank3": []}
    
    for r3_combo in rank3_new:
        if list(r3_combo) not in db_rank3["rank3"]:
            db_rank3["rank3"].append(list(r3_combo))
    with open(WINNING3_PATH, "w", encoding="utf-8") as f:
        json.dump(db_rank3, f, ensure_ascii=False, indent=2)
    msg_rank3 = "3등 조합 업데이트 완료."
    
    msg = f"{msg_rank1}<br>{msg_rank2}<br>{msg_rank3}"

    global ALL_WINNING
    global rank1, rank2, rank3
    rank1 = load_rank(WINNING1_PATH, 'rank1', 6)
    rank2 = load_rank(WINNING2_PATH, 'rank2', 6)
    rank3 = load_rank(WINNING3_PATH, 'rank3', 5)
    ALL_WINNING = {
        "1": set(rank1),
        "2": set(rank2),
        "3": set(rank3)
    }

    logs = []
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except:
        pass
    total_visits = sum(1 for log in logs if log["event"] == "visit")
    total_recs = sum(1 for log in logs if log["event"] == "recommend")
    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg=msg)

# Route for ads.txt (for ad services)
@app.route('/ads.txt')
def ads_txt():
    return app.send_static_file('ads.txt')

# Health check endpoint for deployment environments
@app.route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return "OK", 200

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)
