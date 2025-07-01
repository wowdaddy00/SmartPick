import os
import json
import random
from flask import Flask, render_template, request, jsonify 
from collections import Counter
import datetime
import requests
import itertools
import time 

# Firebase Admin SDK imports
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Flask 앱 초기화
app = Flask(__name__)

# Firebase Firestore 클라이언트 선언 (초기화는 아래 함수에서 수행)
db = None
app_id = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'default-smartpick-app').replace('.', '-')

# 로또 당첨 번호 캐싱을 위한 전역 변수 (Firestore에서 불러온 데이터를 캐시)
cached_lotto_data = {
    'timestamp': 0, # 마지막 캐시 업데이트 시간 (Epoch Time)
    'data': None    # 실제 캐시된 로또 데이터: {'round': int, 'nums': list, 'bonus': int}
}
CACHE_TTL = 3600 # 캐시 유효 시간 (초) - 1시간 (Firestore에서 불러온 데이터 캐시용)

# Kakao JavaScript Key를 환경 변수에서 로드
# Render.com 대시보드에서 KAKAO_JAVASCRIPT_KEY 환경 변수에 카카오 JavaScript 키를 붙여넣으세요.
KAKAO_JAVASCRIPT_KEY = os.environ.get('KAKAO_JAVASCRIPT_KEY', 'YOUR_DEFAULT_KAKAO_JAVASCRIPT_KEY') # 기본값 설정

def initialize_firebase_app():
    """Firebase Admin SDK를 초기화하고 Firestore 클라이언트를 반환합니다."""
    global db 
    global app_id 

    if firebase_admin._apps:
        print("Firebase Admin SDK already initialized.")
        try:
            db = firestore.client() 
            print("Firestore client initialized successfully.")
        except Exception as e:
            print(f"Firestore client re-initialization failed: {e}")
            db = None
        return

    try:
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
        db = None 

# Flask 앱 컨텍스트 외부에서 Firebase 초기화 함수 호출
initialize_firebase_app()

# Firestore에서 로또 당첨 번호 (1, 2, 3등 조합)를 불러오는 함수
# 로컬 JSON 파일 대신 Firestore를 사용합니다.
def load_winning_data_from_firestore():
    global ALL_WINNING, rank1, rank2, rank3
    if db:
        try:
            # Firestore에서 1등 번호 히스토리 컬렉션에서 모든 문서 가져오기
            # 'winning_numbers_rank1' 컬렉션에 각 회차별 문서가 있다고 가정
            rank1_docs = db.collection('winning_numbers_rank1').order_by('round', direction=firestore.Query.DESCENDING).limit(500).stream() # 최근 500회차
            rank1_list = []
            for doc in rank1_docs:
                data = doc.to_dict()
                if 'numbers' in data and isinstance(data['numbers'], list):
                    rank1_list.append(tuple(sorted(data['numbers'])))
            rank1 = rank1_list

            # Firestore에서 2등 조합 히스토리 컬렉션에서 모든 문서 가져오기
            rank2_docs = db.collection('winning_numbers_rank2').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(500).stream() # 최근 업데이트된 500개
            rank2_list = []
            for doc in rank2_docs:
                data = doc.to_dict()
                if 'combination' in data and isinstance(data['combination'], list):
                    rank2_list.append(tuple(sorted(data['combination'])))
            rank2 = rank2_list

            # Firestore에서 3등 조합 히스토리 컬렉션에서 모든 문서 가져오기
            rank3_docs = db.collection('winning_numbers_rank3').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(500).stream() # 최근 업데이트된 500개
            rank3_list = []
            for doc in rank3_docs:
                data = doc.to_dict()
                if 'combination' in data and isinstance(data['combination'], list):
                    rank3_list.append(tuple(sorted(data['combination'])))
            rank3 = rank3_list

            ALL_WINNING = {
                "1": set(rank1),
                "2": set(rank2),
                "3": set(rank3)
            }
            print("Firestore에서 당첨 번호 데이터 로드 완료.")
            return True
        except Exception as e:
            print(f"Firestore에서 당첨 번호 데이터 로드 오류: {e}")
            ALL_WINNING = {"1": set(), "2": set(), "3": set()} # 오류 시 빈 세트로 초기화
            rank1 = []
            rank2 = []
            rank3 = []
            return False
    else:
        print("Firestore DB가 초기화되지 않아 당첨 번호를 로드할 수 없습니다.")
        ALL_WINNING = {"1": set(), "2": set(), "3": set()}
        rank1 = []
        rank2 = []
        rank3 = []
        return False

# 앱 시작 시 당첨 번호 데이터 로드
load_winning_data_from_firestore()

# Function to log events to Firestore
@app.route('/log_event', methods=['POST'])
def handle_log_event():
    if db is None:
        print("Firestore is not initialized. Log event skipped.")
        return jsonify({"status": "error", "message": "Firestore not initialized"}), 500

    try:
        data = request.json
        event = data.get('event')
        detail = data.get('detail')

        sanitized_detail = {}
        if detail:
            for k, v in detail.items():
                if isinstance(v, (list, dict)):
                    sanitized_detail[k] = json.dumps(v, ensure_ascii=False)
                else:
                    sanitized_detail[k] = str(v)

        user_id = f"{app_id}_user_{random.getrandbits(64)}" # 앱 ID 기반 사용자 ID
        log_data = {
            "dt": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "event": event,
            "detail": sanitized_detail, 
            "userId": user_id
        }
        
        # Firestore에 로그 저장 경로: artifacts/{appId}/users/{userId}/logs/{docId}
        doc_ref = db.collection('artifacts').document(app_id).collection('users').document(user_id).collection('logs').add(log_data)
        print(f"Log event '{event}' for user '{user_id}' added to Firestore with ID: {doc_ref[1].id}")
        return jsonify({"status": "success", "log_id": doc_ref[1].id}), 200
    except Exception as e:
        print(f"로그 기록 오류 (Firestore): {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Function to get the latest lottery round number from external API
def get_latest_round_from_api():
    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    # 최근 100회차를 역순으로 확인하여 가장 최신 당첨 번호가 있는 회차를 찾음
    for drw in range(1200, 1100, -1): # 예시: 1200회차부터 1101회차까지
        try:
            resp = requests.get(url + str(drw), timeout=5) # 타임아웃 추가
            resp.raise_for_status() # HTTP 오류 발생 시 예외 발생
            data = resp.json()
            if data.get('returnValue') == 'success' and all(isinstance(data.get(f'drwtNo{i}'), int) for i in range(1, 7)):
                return drw
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"API 요청 또는 JSON 디코딩 오류 (회차 {drw}): {e}")
            continue # 다음 회차 시도
    return None

# Function to fetch latest lotto numbers with bonus number from API (with caching)
# 이 캐싱은 외부 API 호출 빈도를 줄이기 위함이며, Firestore 데이터와는 별개입니다.
def fetch_latest_lotto_from_api_cached(force_update=False):
    global cached_lotto_data

    current_time = time.time()

    if cached_lotto_data['data'] and (current_time - cached_lotto_data['timestamp'] < CACHE_TTL) and not force_update:
        print("Using cached lotto data from API.")
        return cached_lotto_data['data']['round'], \
               cached_lotto_data['data']['nums'], \
               cached_lotto_data['data']['bonus']
    
    print("Fetching new lotto data from external API (or forced update).")
    latest = get_latest_round_from_api()
    if latest is None:
        print("최신 회차 정보를 가져올 수 없습니다.")
        return None, None, None 

    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    try:
        resp = requests.get(url + str(latest), timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"최신 로또 번호 API 호출 오류 (회차 {latest}): {e}")
        return None, None, None
    
    required_keys = [f'drwtNo{i}' for i in range(1, 7)] + ['bnusNo']
    if not all(key in data and isinstance(data[key], int) for key in required_keys):
        print(f"API 응답 데이터 형식이 올바르지 않습니다: {data}")
        return None, None, None

    nums = [data[f'drwtNo{i}'] for i in range(1, 7)]
    bonus = data['bnusNo']

    cached_lotto_data['timestamp'] = current_time
    cached_lotto_data['data'] = {
        'round': latest,
        'nums': nums,
        'bonus': bonus
    }
    
    return latest, nums, bonus

# Function to generate combinations for 2nd and 3rd rank numbers
def make_rank2_3(nums, bonus):
    combis = list(itertools.combinations(nums, 5))
    rank2 = []
    rank3 = []
    for c in combis:
        # 5개 번호와 보너스 번호가 일치하는 경우 2등 조합
        if bonus in c:
            rank2.append(tuple(sorted(list(c) + [bonus]))) # 2등은 5개 번호 + 보너스 번호
        else:
            rank3.append(tuple(sorted(c))) # 3등은 5개 번호
    return rank2, rank3

# Function to get frequently appearing numbers from recent N draws
def get_hot_numbers(n=5):
    # rank1 데이터는 이제 Firestore에서 로드됩니다.
    all_nums = []
    # rank1의 마지막 n개 회차에서 번호를 가져옴 (최신 데이터는 리스트의 끝에 있다고 가정)
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
        exclude_db.update(ALL_WINNING.get(r, set())) # ALL_WINNING은 이제 Firestore에서 로드된 데이터

    hot_numbers_to_exclude = get_hot_numbers(exclude_hot_n) if exclude_hot_n else set()
    
    while len(results) < count:
        nums_list = random.sample(range(1, 46), 6)
        nums = set(nums_list) # set으로 변환하여 교집합 연산 용이하게

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
        current_combo_sorted_tuple = tuple(sorted(nums_list))
        
        if exclude_db:
            # 1등 제외
            if current_combo_sorted_tuple in ALL_WINNING.get("1", set()):
                tries += 1
                if tries > 30000: break
                continue
            
            # 2등 제외 (5개 번호 + 보너스 번호 형태)
            # 2등은 6개 번호 중 5개 + 보너스 번호가 일치해야 하므로, 생성된 6개 번호와 보너스 번호의 조합을 확인해야 함
            # 여기서는 ALL_WINNING["2"]에 저장된 6개 번호 조합과 직접 비교
            if current_combo_sorted_tuple in ALL_WINNING.get("2", set()):
                tries += 1
                if tries > 30000: break
                continue

            # 3등 제외 (5개 번호 일치)
            is_rank3_match = False
            for combo in itertools.combinations(nums_list, 5):
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
        if sorted(list(nums)) in results: # results는 리스트의 리스트이므로 sorted(list(nums))와 비교
            tries += 1
            if tries > 30000: break
            continue
            
        results.append(sorted(list(nums)))

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
    numbers = None
    error = ""
    
    # 메인 페이지에서는 Firestore에서 저장된 최신 당첨 번호를 불러옵니다.
    # fetch_latest_lotto_from_api_cached() 대신 Firestore에서 직접 가져오도록 변경
    latest_winning_data = None
    if db:
        try:
            doc_ref = db.collection('lotto_data').document('latest_numbers')
            doc = doc_ref.get()
            if doc.exists:
                latest_winning_data = doc.to_dict()
                print(f"메인 페이지: Firestore에서 최신 당첨 번호 로드: {latest_winning_data}")
            else:
                print("메인 페이지: Firestore에 최신 당첨 번호 문서가 없습니다.")
        except Exception as e:
            print(f"메인 페이지: Firestore에서 최신 당첨 번호 로드 오류: {e}")
    
    latest_round = latest_winning_data.get('round') if latest_winning_data else None
    winning_nums = latest_winning_data.get('numbers') if latest_winning_data else None
    bonus_num = latest_winning_data.get('bonus') if latest_winning_data else None

    total_recs_count = 0
    if db: 
        try:
            stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
            stats_doc = stats_doc_ref.get()
            if stats_doc.exists:
                total_recs_count = stats_doc.to_dict().get('total_recommendations', 0)
            else:
                stats_doc_ref.set({'total_recommendations': 0})
                total_recs_count = 0 
        except Exception as e:
            print(f"Firestore에서 누적 추천 건수 가져오기 오류: {e}")
            total_recs_count = 0 
    else:
        print("Firestore DB not available for fetching total recommendations.")


    if request.method == "POST":
        numbers = generate_numbers(count=1, exclude_ranks=['1', '2', '3'])

        if db and numbers: 
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
        total_recs_count=total_recs_count 
    )

# New Route for choosing recommendation type
@app.route('/choose_recommendation')
def choose_recommendation():
    return render_template('choose_recommendation.html')

# Route for the detailed filtered recommendation page
@app.route("/filter", methods=["GET", "POST"])
def detailed_filter_page():
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
                
                if db and numbers: 
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
                    
                    if db and numbers: 
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
    try:
        data = request.json
        lotto_numbers = data.get('numbers')
        if not lotto_numbers or not isinstance(lotto_numbers, list) or len(lotto_numbers) != 6:
            return jsonify({"error": "유효한 로또 번호 6개를 제공해주세요."}), 400

        numbers_str = ", ".join(map(str, sorted(lotto_numbers)))
        
        prompt = f"다음 로또 번호 {numbers_str}에 대한 짧고 재미있는 로또 당첨 시나리오를 작성해주세요. 예를 들어, 이 번호들로 복권에 당첨되어 어떤 일이 일어났는지 상상력을 발휘하여 이야기해주세요. 최대한 긍정적이고 유머러스하게 작성해 주세요. 3-4문장으로 간결하게 작성해주세요."

        api_key = os.environ.get('GEMINI_API_KEY', '') 
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
        response.raise_for_status() 
        
        result = response.json()
        
        story = "스토리를 생성하지 못했습니다."
        if result.get('candidates') and len(result['candidates']) > 0 and \
           result['candidates'][0].get('content') and \
           result['candidates'][0]['content'].get('parts') and \
           len(result['candidates'][0]['content'].get('parts')) > 0:
            story = result['candidates'][0]['content']['parts'][0]['text']
        else:
            print("Gemini API 응답 구조가 예상과 다릅니다:", result) 
            
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
    return render_template('about.html')

# Route for the Privacy Policy page
@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Route for the Disclaimer page
@app.route('/disclaimer')
def disclaimer():
    return render_template('disclaimer.html')

# Route for the Contact page
@app.route('/contact')
def contact():
    return render_template('contact.html')

# Route for the Statistics page
@app.route('/stats')
def stats():
    recent_n = 10 
    all_nums = [] 
    # rank1은 이제 Firestore에서 로드되므로, 데이터가 있는지 확인
    if rank1:
        for row in rank1[-recent_n:]:
            all_nums.extend(row)
    
    freq = dict(Counter(all_nums))
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
    msg = "" # 메시지 초기화
    if db: 
        try:
            all_logs = []
            # Firestore에서 로그를 가져올 때, 사용자별 컬렉션에서 가져오도록 수정
            users_ref = db.collection('artifacts').document(app_id).collection('users').stream()
            for user_doc in users_ref:
                user_logs_ref = db.collection('artifacts').document(app_id).collection('users').document(user_doc.id).collection('logs')
                # timestamp 필드를 기준으로 내림차순 정렬
                user_logs = user_logs_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream() 
                for log in user_logs:
                    log_data = log.to_dict()
                    if 'timestamp' in log_data and log_data['timestamp']: 
                        # Firestore Timestamp 객체를 datetime 객체로 변환 후 포맷팅
                        log_data['dt_formatted'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S') 
                    elif 'dt' in log_data: # 이전 형식의 dt 필드도 처리
                        log_data['dt_formatted'] = log_data['dt'] 
                    all_logs.append(log_data)
            # 모든 사용자 로그를 합쳐서 다시 시간 기준으로 정렬
            logs = sorted(all_logs, key=lambda x: x.get('dt_formatted', ''), reverse=True) 

        except Exception as e:
            print(f"관리자 로그 가져오기 오류 (Firestore): {e}")
            msg = f"로그 로드 오류: {e}" # 오류 메시지 추가
            pass
    else:
        print("Firestore DB not available for fetching admin logs.")
        msg = "Firestore DB가 초기화되지 않아 로그를 가져올 수 없습니다."

    total_visits = sum(1 for log in logs if log["event"]=="visit")
    total_recs = sum(1 for log in logs if log["event"]=="recommend")
    
    today_recs_admin = 0
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    for log in logs:
        if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(today_str):
            today_recs_admin += 1

    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg)

# Route to update winning numbers (admin functionality)
@app.route("/update_winning", methods=["POST"])
def update_winning():
    pw = request.form.get("pw")
    
    if pw != "1234":
        # 비밀번호 틀렸을 때도 로그와 통계 데이터를 가져와서 템플릿에 전달
        logs = []
        msg = "비밀번호가 틀렸습니다."
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
                msg += f"<br>로그 로드 오류: {e}"
                pass
        
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))
        
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg)

    # 외부 API에서 최신 로또 번호 가져오기
    latest, nums, bonus = fetch_latest_lotto_from_api_cached(force_update=True) 
    
    if latest is None or nums is None or bonus is None:
        msg = "아직 최신 회차 당첨번호가 공개되지 않았습니다.<br>잠시 후 다시 시도해 주세요."
        logs = [] # 메시지 전달을 위해 로그 다시 로드
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
                msg += f"<br>로그 로드 오류: {e}"
                pass
        
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))

        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg)
        
    # --- Update Winning Data in Firestore ---
    msg_rank1 = ""
    msg_rank2 = ""
    msg_rank3 = ""

    if db:
        try:
            # 1등 번호 저장 (회차별 문서)
            rank1_doc_ref = db.collection('winning_numbers_rank1').document(str(latest))
            if not rank1_doc_ref.get().exists:
                rank1_doc_ref.set({
                    'round': latest,
                    'numbers': sorted(nums),
                    'bonus': bonus,
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
                msg_rank1 = f"{latest}회차 1등 번호 {nums} 저장 완료!"
            else:
                msg_rank1 = f"1등 번호 (회차 {latest})는 이미 최신으로 반영되어 있습니다."
            
            # 최신 1등 번호, 보너스 번호를 'lotto_data/latest_numbers' 문서에 저장 (메인 페이지용)
            db.collection('lotto_data').document('latest_numbers').set({
                'round': latest,
                'numbers': sorted(nums),
                'bonus': bonus,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            print(f"Firestore 'lotto_data/latest_numbers' 업데이트 완료: {latest}회차")

            # 2등 및 3등 조합 생성
            rank2_new, rank3_new = make_rank2_3(nums, bonus)

            # 2등 조합 저장 (각 조합별 문서 또는 배열에 추가)
            # 여기서는 각 조합을 고유 ID로 문서화하여 중복 방지
            for r2_combo in rank2_new:
                combo_id = "_".join(map(str, r2_combo)) # 조합을 문자열 ID로
                rank2_combo_doc_ref = db.collection('winning_numbers_rank2').document(combo_id)
                if not rank2_combo_doc_ref.get().exists:
                    rank2_combo_doc_ref.set({
                        'combination': list(r2_combo), # 튜플을 리스트로 저장
                        'round': latest,
                        'updated_at': firestore.SERVER_TIMESTAMP
                    })
            msg_rank2 = "2등 조합 업데이트 완료."

            # 3등 조합 저장
            for r3_combo in rank3_new:
                combo_id = "_".join(map(str, r3_combo))
                rank3_combo_doc_ref = db.collection('winning_numbers_rank3').document(combo_id)
                if not rank3_combo_doc_ref.get().exists:
                    rank3_combo_doc_ref.set({
                        'combination': list(r3_combo),
                        'round': latest,
                        'updated_at': firestore.SERVER_TIMESTAMP
                    })
            msg_rank3 = "3등 조합 업데이트 완료."
            
            # Firestore 업데이트 후 ALL_WINNING 및 rank1, rank2, rank3 전역 변수 새로고침
            load_winning_data_from_firestore()

            msg = f"{msg_rank1}<br>{msg_rank2}<br>{msg_rank3}"

        except Exception as e:
            print(f"Firestore 업데이트 중 오류 발생: {e}")
            msg = f"로또 번호 업데이트 오류 (Firestore): {e}"
    else:
        msg = "Firestore DB가 초기화되지 않아 로또 번호를 업데이트할 수 없습니다."

    # 관리자 페이지에 표시할 로그와 통계 다시 로드
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

# New Route for Lotto DNA Test page
@app.route('/lotto-dna-test')
def lotto_dna_test_page():
    # Kakao JavaScript Key를 템플릿에 전달
    return render_template('lotto_type_test.html', kakao_js_key=KAKAO_JAVASCRIPT_KEY)

# New API endpoint to generate Lotto DNA numbers
@app.route('/generate_dna_lotto_numbers', methods=['POST'])
def generate_dna_lotto_numbers():
    try:
        # 클라이언트에서 넘어온 DNA 유형 (현재는 사용하지 않고 무작위 생성)
        # dna_type = request.json.get('dna_type') 
        
        # 무작위 로또 번호 6개 생성 (1부터 45까지)
        numbers = sorted(random.sample(range(1, 46), 6))
        
        return jsonify({"numbers": numbers}), 200
    except Exception as e:
        print(f"로또 DNA 번호 생성 오류: {e}")
        return jsonify({"error": "로또 DNA 번호 생성에 실패했습니다."}), 500

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=os.environ.get('PORT', 5000))
