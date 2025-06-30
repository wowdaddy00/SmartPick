import os
import json
import random
from flask import Flask, render_template, request, jsonify
from collections import Counter
import datetime
import requests
import itertools

# Firebase Admin SDK imports
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Flask 앱 초기화
app = Flask(__name__)

# Firebase Firestore 클라이언트 선언 (초기화는 아래 함수에서 수행)
db = None
app_id = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'default-smartpick-app').replace('.', '-')

def initialize_firebase_app():
    """Firebase Admin SDK를 초기화하고 Firestore 클라이언트를 반환합니다."""
    global db # 전역 변수 db를 수정하기 위해 global 선언
    global app_id # 전역 변수 app_id를 수정하기 위해 global 선언

    if firebase_admin._apps:
        print("Firebase Admin SDK already initialized.")
        db = firestore.client() # 이미 초기화된 경우 클라이언트만 가져옴
        return

    try:
        # Render 환경 변수에서 서비스 계정 키 JSON 문자열을 가져옴
        firebase_service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
        
        if firebase_service_account_json:
            cred_dict = json.loads(firebase_service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK initialized successfully from environment variable.")
            db = firestore.client()
            print("Firestore client initialized successfully.")
        else:
            print("FIREBASE_SERVICE_ACCOUNT_KEY environment variable not found. Firebase Admin SDK will not be initialized.")
            print("Firestore features will be unavailable.")

    except Exception as e:
        print(f"Firebase Admin SDK initialization failed: {e}")
        db = None # 초기화 실패 시 db를 None으로 설정하여 사용하지 않도록 함

# Flask 앱 컨텍스트 외부에서 Firebase 초기화 함수 호출
# 이 함수는 앱이 로드될 때 (gunicorn에 의해) 한 번만 호출되도록 의도됩니다.
initialize_firebase_app()

# Function to log events to Firestore
def log_event(event, detail=None):
    if db is None:
        print(f"Firestore is not initialized. Log event '{event}' skipped.")
        return

    try:
        user_id = f"{app_id}_user_{random.getrandbits(64)}" # 앱 ID 기반 사용자 ID
        
        log_data = {
            "dt": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "event": event,
            "detail": detail or {},
            "userId": user_id
        }
        # 개인 로그는 /artifacts/{appId}/users/{userId}/logs 컬렉션에 저장
        # NOTE: 이 예시에서는 모든 로그가 Firestore에 저장됩니다.
        # 실제 사용자가 늘어날 경우 비용 문제가 발생할 수 있으므로,
        # 'recommend' 이벤트와 같은 주요 통계만 Firestore에 저장하고
        # 'visit'과 같은 빈번한 이벤트는 로컬 로그 파일 또는 집계된 형태로 저장하는 것을 고려해야 합니다.
        doc_ref = db.collection('artifacts').document(app_id).collection('users').document(user_id).collection('logs').add(log_data)
        print(f"Log event '{event}' for user '{user_id}' added to Firestore with ID: {doc_ref[1].id}")
    except Exception as e:
        print(f"로그 기록 오류 (Firestore): {e}")

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

        if tries > 300000:
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
    
    # 최신 당첨 번호 가져오기
    latest_round, winning_nums, bonus_num = fetch_latest_lotto_with_bonus()

    # Firestore에서 누적 추천 건수 가져오기
    total_recs_count = 0
    if db: # db가 초기화되었을 때만 Firestore 사용
        try:
            # public/data/app_stats 컬렉션에서 통계 문서 가져오기 (만약 통계가 별도 문서에 집계된다면)
            # artifacts/{appId}/public/data/app_stats/recommendation_counts 문서에서 count 필드 가져오기
            stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
            stats_doc = stats_doc_ref.get()
            if stats_doc.exists:
                total_recs_count = stats_doc.to_dict().get('total_recommendations', 0)
            else:
                # 문서가 없으면 초기값 0으로 설정하고 문서 생성 (필요하다면)
                stats_doc_ref.set({'total_recommendations': 0})
                total_recs_count = 0 # 새로 만들었으니 0으로 시작
        except Exception as e:
            print(f"Firestore에서 누적 추천 건수 가져오기 오류: {e}")
            total_recs_count = 0 # 오류 발생 시 0으로 설정
    else:
        print("Firestore DB not available for fetching total recommendations.")


    if request.method == "POST":
        numbers = generate_numbers(count=1, exclude_ranks=['1', '2', '3'])
        log_event("recommend", {
            "page": "index_premium_quick",
            "numbers": numbers,
            "user_ip": request.remote_addr
        })

        # 추천 시 Firestore에 누적 카운트 증가
        if db and numbers: # db가 초기화되었고 번호가 성공적으로 생성되었을 때만
            try:
                stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
                stats_doc_ref.update({
                    'total_recommendations': firestore.Increment(1),
                    'last_updated': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"Firestore 누적 추천 건수 업데이트 오류: {e}")

        if not numbers:
            error = "추천 가능한 프리미엄 번호가 없습니다. (필터를 줄이거나 다시 시도해주세요)"
            
    return render_template(
        "index.html",
        numbers=numbers,
        error=error,
        latest_round=latest_round,
        winning_nums=winning_nums,
        bonus_num=bonus_num,
        total_recs_count=total_recs_count # 누적 추천 건수 전달
    )

# New Route for choosing recommendation type
@app.route('/choose_recommendation')
def choose_recommendation():
    log_event("visit", {"page": "choose_recommendation"})
    return render_template('choose_recommendation.html')

# Route for the detailed filtered recommendation page
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
                    error = "조건에 맞는 추천번호가 없습니다. (필터를 줄이거나 다시 시도해주세요)"
                
                log_event("recommend", {
                    "page": "detailed_filter",
                    "numbers": numbers,
                    "user_ip": request.remote_addr,
                    "condition": dict(request.form)
                })

                # 추천 시 Firestore에 누적 카운트 증가
                if db and numbers: # db가 초기화되었고 번호가 성공적으로 생성되었을 때만
                    try:
                        stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
                        stats_doc_ref.update({
                            'total_recommendations': firestore.Increment(1),
                            'last_updated': firestore.SERVER_TIMESTAMP
                        })
                    except Exception as e:
                        print(f"Firestore 누적 추천 건수 업데이트 오류 (detailed filter): {e}")

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
                hot_numbers_set = get_hot_numbers(hot_pick_n)
                
                generated_numbers = []
                for _ in range(count):
                    if len(hot_numbers_set) < 6:
                        error = "선택된 회차의 인기 번호가 6개 미만입니다. 다른 회차를 선택하거나 필터를 줄여주세요."
                        break
                    
                    current_set = sorted(random.sample(list(hot_numbers_set), 6))
                    generated_numbers.append(current_set)
                
                if not error: 
                    numbers = generated_numbers
                    form = dict(request.form)
                    
                    log_event("recommend", {
                        "page": "hotpick_recommendation",
                        "numbers": numbers,
                        "user_ip": request.remote_addr,
                        "condition": dict(request.form)
                    })

                    # 추천 시 Firestore에 누적 카운트 증가
                    if db and numbers: # db가 초기화되었고 번호가 성공적으로 생성되었을 때만
                        try:
                            stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
                            stats_doc_ref.update({
                                'total_recommendations': firestore.Increment(1),
                                'last_updated': firestore.SERVER_TIMESTAMP
                            })
                        except Exception as e:
                            print(f"Firestore 누적 추천 건수 업데이트 오류 (hotpick): {e}")

            else:
                error = "인기 번호 추천 주기를 선택해주세요."
            
        except Exception as e:
            error = f"입력값 오류: {e}"
    
    return render_template("hotpick.html", numbers=numbers, error=error, form=form)


# 로또 번호 스토리 생성 LLM 통합 라우트 (활성화됨)
@app.route('/generate_lotto_story', methods=['POST'])
def generate_lotto_story():
    log_event("llm_story_request", {"user_ip": request.remote_addr})
    try:
        data = request.json
        lotto_numbers = data.get('numbers')
        if not lotto_numbers or not isinstance(lotto_numbers, list) or len(lotto_numbers) != 6:
            return jsonify({"error": "유효한 로또 번호 6개를 제공해주세요."}), 400

        numbers_str = ", ".join(map(str, sorted(lotto_numbers)))
        
        # Gemini API를 위한 프롬프트 구성
        prompt = f"다음 로또 번호 {numbers_str}에 대한 짧고 재미있는 로또 당첨 시나리오를 작성해주세요. 예를 들어, 이 번호들로 복권에 당첨되어 어떤 일이 일어났는지 상상력을 발휘하여 이야기해주세요. 최대한 긍정적이고 유머러스하게 작성해 주세요. 3-4문장으로 간결하게 작성해주세요."

        # Gemini API 호출 (API 키는 Canvas 환경에서 자동으로 제공됩니다.)
        api_key = os.environ.get('GEMINI_API_KEY', '') # Render 환경 변수에서 API 키 가져오기 (필요하다면)
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ]
        }

        response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status() # HTTP 오류 (4xx, 5xx) 발생 시 예외 처리
        
        result = response.json()
        
        story = "스토리를 생성하지 못했습니다."
        if result.get('candidates') and len(result['candidates']) > 0 and \
           result['candidates'][0].get('content') and \
           result['candidates'][0]['content'].get('parts') and \
           len(result['candidates'][0]['content'].get('parts')) > 0:
            story = result['candidates'][0]['content']['parts'][0]['text']
        else:
            print("Gemini API 응답 구조가 예상과 다릅니다:", result) # 디버깅을 위한 출력
            
        log_event("llm_story_response", {"numbers": lotto_numbers, "story": story})
        return jsonify({"story": story})

    except requests.exceptions.RequestException as e:
        print(f"Gemini API 요청 중 오류 발생: {e}")
        return jsonify({"error": "스토리 생성 서비스에 문제가 발생했습니다. 잠시 후 다시 시도해주세요."}), 500
    except Exception as e:
        print(f"로또 스토리 생성 중 예기치 않은 오류 발생: {e}")
        return jsonify({"error": "스토리 생성 중 알 수 없는 오류가 발생했습니다."}), 500


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
    if db: # db가 초기화되었을 때만 Firestore 사용
        try:
            all_logs = []
            # 모든 사용자의 로그를 가져오는 것은 비효율적일 수 있으므로 주의.
            # 실제 운영에서는 특정 기간이나 제한된 수의 로그만 가져와야 함.
            users_ref = db.collection('artifacts').document(app_id).collection('users').stream()
            for user_doc in users_ref:
                user_logs_ref = db.collection('artifacts').document(app_id).collection('users').document(user_doc.id).collection('logs')
                user_logs = user_logs_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream() # 최근 100개 로그만 가져오기
                for log in user_logs:
                    log_data = log.to_dict()
                    # timestamp 필드가 존재하면 datetime 객체로 변환
                    if 'timestamp' in log_data and log_data['timestamp']: # None 체크 추가
                        log_data['dt_formatted'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S') # datetime 객체를 문자열로 변환
                    elif 'dt' in log_data:
                        log_data['dt_formatted'] = log_data['dt'] # 기존 dt 사용
                    all_logs.append(log_data)
            logs = sorted(all_logs, key=lambda x: x.get('dt_formatted', ''), reverse=True) # 최신 로그가 위에 오도록 정렬

        except Exception as e:
            print(f"관리자 로그 가져오기 오류 (Firestore): {e}")
            pass
    else:
        print("Firestore DB not available for fetching admin logs.")

    total_visits = sum(1 for log in logs if log["event"]=="visit")
    total_recs = sum(1 for log in logs if log["event"]=="recommend")
    
    today_recs_admin = 0
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    for log in logs:
        if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(today_str):
            today_recs_admin += 1

    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin)

# Route to update winning numbers (admin functionality)
@app.route("/update_winning", methods=["POST"])
def update_winning():
    pw = request.form.get("pw")
    
    if pw != "1234":
        logs = []
        if db:
            try:
                all_logs = []
                users_ref = db.collection('artifacts').document(app_id).collection('users').stream()
                for user_doc in users_ref:
                    user_logs_ref = db.collection('artifacts').document(app_id).collection('users').document(user_doc.id).collection('logs')
                    user_logs = user_logs_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream()
                    for log in user_logs:
                        log_data = log.to_dict()
                        if 'timestamp' in log_data and log_data['timestamp']:
                            log_data['dt_formatted'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                        elif 'dt' in log_data:
                            log_data['dt_formatted'] = log_data['dt']
                        all_logs.append(log_data)
                logs = sorted(all_logs, key=lambda x: x.get('dt_formatted', ''), reverse=True)
            except Exception as e:
                print(f"관리자 로그 가져오기 오류 (Firestore): {e}")
                pass
        
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))
        
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg="비밀번호가 틀렸습니다.")

    latest, nums, bonus = fetch_latest_lotto_with_bonus()
    
    if latest is None or nums is None or bonus is None:
        msg = "아직 최신 회차 당첨번호가 공개되지 않았습니다.<br>잠시 후 다시 시도해 주세요."
        logs = []
        if db:
            try:
                all_logs = []
                users_ref = db.collection('artifacts').document(app_id).collection('users').stream()
                for user_doc in users_ref:
                    user_logs_ref = db.collection('artifacts').document(app_id).collection('users').document(user_doc.id).collection('logs')
                    user_logs = user_logs_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream()
                    for log in user_logs:
                        log_data = log.to_dict()
                        if 'timestamp' in log_data and log_data['timestamp']:
                            log_data['dt_formatted'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                        elif 'dt' in log_data:
                            log_data['dt_formatted'] = log_data['dt']
                        all_logs.append(log_data)
                logs = sorted(all_logs, key=lambda x: x.get('dt_formatted', ''), reverse=True)
            except Exception as e:
                print(f"관리자 로그 가져오기 오류 (Firestore): {e}")
                pass
        
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))

        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg)
        
    # --- Update Rank 1 Data ---
    try:
        os.makedirs(os.path.dirname(WINNING1_PATH), exist_ok=True)
        with open(WINNING1_PATH, encoding="utf-8") as f:
            db_rank1 = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"{WINNING1_PATH} 파일 읽기/디코딩 에러 (새 파일 생성):", e)
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
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"{WINNING2_PATH} 파일 읽기/디코딩 에러 (새 파일 생성):", e)
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
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"{WINNING3_PATH} 파일 읽기/디코딩 에러 (새 파일 생성):", e)
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
    if db:
        try:
            all_logs = []
            users_ref = db.collection('artifacts').document(app_id).collection('users').stream()
            for user_doc in users_ref:
                user_logs_ref = db.collection('artifacts').document(app_id).collection('users').document(user_doc.id).collection('logs')
                user_logs = user_logs_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream()
                for log in user_logs:
                    log_data = log.to_dict()
                    if 'timestamp' in log_data and log_data['timestamp']:
                        log_data['dt_formatted'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                    elif 'dt' in log_data:
                        log_data['dt_formatted'] = log_data['dt']
                    all_logs.append(log_data)
            logs = sorted(all_logs, key=lambda x: x.get('dt_formatted', ''), reverse=True)
        except Exception as e:
            print(f"관리자 로그 가져오기 오류 (Firestore): {e}")
            pass
    
    total_visits = sum(1 for log in logs if log["event"] == "visit")
    total_recs = sum(1 for log in logs if log["event"] == "recommend")
    today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))

    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg)

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
    # Flask 개발 서버 실행 (Gunicorn은 프로덕션용)
    app.run(debug=True, host='0.0.0.0', port=os.environ.get('PORT', 5000))

