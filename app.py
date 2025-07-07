import os
import json
import random
from flask import Flask, render_template, request, jsonify, Response, url_for
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

    print("Firebase Admin SDK 초기화 시도...") # 디버그 로그
    if firebase_admin._apps:
        print("Firebase Admin SDK 이미 초기화됨.")
        try:
            db = firestore.client()
            print("Firestore 클라이언트 재확인 성공.")
        except Exception as e:
            print(f"Firestore 클라이언트 재확인 실패: {e}")
            db = None
        return

    try:
        firebase_service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')

        if firebase_service_account_json:
            print("FIREBASE_SERVICE_ACCOUNT_KEY 환경 변수 감지됨.") # 디버그 로그
            cred_dict = json.loads(firebase_service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK 초기화 성공.") # 디버그 로그
            db = firestore.client()
            print("Firestore 클라이언트 초기화 성공.") # 디버그 로그
        else:
            print("FIREBASE_SERVICE_ACCOUNT_KEY 환경 변수를 찾을 수 없습니다. Firebase Admin SDK가 초기화되지 않습니다.") # 디버그 로그
            print("Firestore 기능은 사용할 수 없습니다.")

    except Exception as e:
        print(f"Firebase Admin SDK 초기화 실패: {e}") # 디버그 로그
        db = None

# Flask 앱 컨텍스트 외부에서 Firebase 초기화 함수 호출
initialize_firebase_app()

# Firestore에서 로또 당첨 번호 (1, 2, 3등 조합)를 불러오는 함수
def load_winning_data_from_firestore():
    global ALL_WINNING, rank1, rank2, rank3
    print("Firestore에서 당첨 번호 데이터 로드 시도 중...") # 디버그 로그
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
            print(f"Firestore에서 1등 조합 {len(rank1_list)}개 로드 완료.") # 디버그 로그

            # Firestore에서 2등 조합 히스토리 컬렉션에서 모든 문서 가져오기
            rank2_docs = db.collection('winning_numbers_rank2').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(500).stream() # 최근 업데이트된 500개
            rank2_list = []
            for doc in rank2_docs:
                data = doc.to_dict()
                if 'combination' in data and isinstance(data['combination'], list):
                    rank2_list.append(tuple(sorted(data['combination'])))
            rank2 = rank2_list
            print(f"Firestore에서 2등 조합 {len(rank2_list)}개 로드 완료.") # 디버그 로그

            # Firestore에서 3등 조합 히스토리 컬렉션에서 모든 문서 가져오기
            rank3_docs = db.collection('winning_numbers_rank3').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(500).stream() # 최근 업데이트된 500개
            rank3_list = []
            for doc in rank3_docs:
                data = doc.to_dict()
                if 'combination' in data and isinstance(data['combination'], list):
                    rank3_list.append(tuple(sorted(data['combination'])))
            rank3 = rank3_list
            print(f"Firestore에서 3등 조합 {len(rank3_list)}개 로드 완료.") # 디버그 로그

            ALL_WINNING = {
                "1": set(rank1),
                "2": set(rank2),
                "3": set(rank3)
            }
            print(f"ALL_WINNING 데이터 세트 크기: 1등:{len(ALL_WINNING['1'])}, 2등:{len(ALL_WINNING['2'])}, 3등:{len(ALL_WINNING['3'])}") # 디버그 로그
            print("Firestore에서 당첨 번호 데이터 로드 완료.")
            return True
        except Exception as e:
            print(f"Firestore에서 당첨 번호 데이터 로드 오류: {e}") # 디버그 로그
            ALL_WINNING = {"1": set(), "2": set(), "3": set()} # 오류 시 빈 세트로 초기화
            rank1 = []
            rank2 = []
            rank3 = []
            return False
    else:
        print("Firestore DB가 초기화되지 않아 당첨 번호를 로드할 수 없습니다.") # 디버그 로그
        ALL_WINNING = {"1": set(), "2": set(), "3": set()}
        rank1 = []
        rank2 = []
        rank3 = []
        return False

# 앱 시작 시 당첨 번호 데이터 로드
load_winning_data_from_firestore()

# Function to load winning data from winning_numbers_full.json file
def load_winning_data_from_json(file_path):
    try:
        # winning_numbers_full.json 파일이 static 디렉토리에 있다고 가정
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('rank1', [])
    except FileNotFoundError:
        print(f"Error: {file_path} not found. Please ensure it's in the correct directory.")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not parse {file_path}.")
        return []

# Function to load winning data for specific rank from JSON file
def load_rank_data_from_json(file_path, rank_key):
    try:
        # JSON 파일이 static 디렉토리에 있다고 가정
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(rank_key, [])
    except FileNotFoundError:
        print(f"Error: {file_path} not found. Please ensure it's in the correct directory.")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not parse {file_path}.")
        return []


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
    # rank1이 비어있을 경우를 대비하여 조건 추가
    if rank1:
        # n이 rank1의 길이보다 크면 rank1의 모든 요소를 사용
        start_index = max(0, len(rank1) - n)
        for row in rank1[start_index:]:
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

            # 2등 제외 (5개 번호와 보너스 번호가 일치하는 형태)
            # ALL_WINNING["2"]에 저장된 것은 6개 번호 조합 (5개 당첨 + 보너스)
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
        total_recs_count=total_recs_count,
        now=datetime.datetime.now() # <--- 추가
    )

# New Route for choosing recommendation type
@app.route('/choose_recommendation')
def choose_recommendation():
    return render_template('choose_recommendation.html', now=datetime.datetime.now()) # <--- 추가

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

    return render_template("filter.html", numbers=numbers, error=error, form=form, now=datetime.datetime.now()) # <--- 추가

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

    return render_template("hotpick.html", numbers=numbers, error=error, form=form, now=datetime.datetime.now()) # <--- 추가


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
    return render_template('about.html', now=datetime.datetime.now()) # <--- 추가

# Route for the Privacy Policy page
@app.route('/privacy')
def privacy():
    return render_template('privacy.html', now=datetime.datetime.now()) # <--- 추가

# Route for the Disclaimer page
@app.route('/disclaimer')
def disclaimer():
    return render_template('disclaimer.html', now=datetime.datetime.now()) # <--- 추가

# Route for the Contact page
@app.route('/contact')
def contact():
    return render_template('contact.html', now=datetime.datetime.now()) # <--- 추가

# Route for the Statistics page
@app.route('/stats')
def stats():
    recent_n = 10
    all_nums = []
    # rank1은 이제 Firestore에서 로드되므로, 데이터가 있는지 확인
    if rank1:
        # n이 rank1의 길이보다 크면 rank1의 모든 요소를 사용
        start_index = max(0, len(rank1) - recent_n)
        for row in rank1[start_index:]:
            all_nums.extend(row)

    freq = dict(Counter(all_nums))
    for n in range(1, 46):
        freq.setdefault(n, 0)
    freq = dict(sorted(freq.items()))

    print(f"/stats 라우트에서 freq 데이터 생성 완료: {freq}") # 디버그 로그 추가
    return render_template('stats.html', freq_json=freq, recent_n=recent_n, now=datetime.datetime.now()) # <--- 추가

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

    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg, now=datetime.datetime.now()) # <--- 추가

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

        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg, now=datetime.datetime.now()) # <--- 추가

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

        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg, now=datetime.datetime.now()) # <--- 추가

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

    # 비밀번호가 맞았을 때도 로그와 통계 데이터를 가져와서 템플릿에 전달
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
            msg += f"<br>로그 로드 오류: {e}"
            pass

    total_visits = sum(1 for log in logs if log["event"] == "visit")
    total_recs = sum(1 for log in logs if log["event"] == "recommend")
    today_recs_admin = sum(1 for log in logs if log["event"] == "recommend" and log.get("dt_formatted", "").startswith(datetime.datetime.now().strftime('%Y-%m-%d')))

    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, today_recs=today_recs_admin, msg=msg, now=datetime.datetime.now()) # <--- 추가

# --- START: NEW Admin Route for Past Rank1 Upload ---
@app.route('/admin_upload_past_rank1', methods=['POST'])
def admin_upload_past_rank1():
    pw = request.form.get("pw")
    if pw != "1234":
        return jsonify({"status": "error", "message": "관리자 비밀번호가 틀렸습니다."}), 403

    if db is None:
        return jsonify({"status": "error", "message": "Firestore DB가 초기화되지 않았습니다."}), 500

    try:
        # JSON 파일에서 과거 1등 데이터 로드
        # 파일 경로를 static 폴더 내부로 수정
        past_rank1_data = load_winning_data_from_json('static/winning_numbers_full.json') # <--- 이 부분 수정
        if not past_rank1_data:
            return jsonify({"status": "error", "message": "업로드할 1등 과거 데이터가 없습니다. 'winning_numbers_full.json' 파일 확인."}), 400

        # Firestore에서 가장 높은 회차 번호 가져오기 (이미 있는 경우)
        latest_round_doc = db.collection('winning_numbers_rank1').order_by('round', direction=firestore.Query.DESCENDING).limit(1).stream()
        current_max_round = 0
        for doc in latest_round_doc:
            current_max_round = max(current_max_round, doc.to_dict().get('round', 0))

        # JSON 데이터의 길이를 기반으로 시작 회차 계산
        # 예시: JSON에 300개의 데이터가 있고, 최신 회차가 1179라면,
        # 가장 오래된 데이터는 1179 - 299 = 880회차가 됩니다.
        # JSON 파일에 회차 정보가 없으므로, 편의상 가장 최신 회차부터 역순으로 회차를 부여.
        # 현재 코드의 latest 변수를 사용하여 정확한 회차를 부여할 수도 있습니다.
        # 여기서는 JSON 데이터의 마지막 조합이 최신 회차라고 가정하고, 그 이전 회차들을 역순으로 채워 넣음.
        # 만약 current_max_round가 0이면 (아무 데이터도 없으면),
        # JSON 데이터의 마지막 요소를 가장 최신 회차로 간주하고, 그 이전 회차들을 순서대로 부여합니다.
        
        # 임의의 시작 회차 (만약 Firestore에 데이터가 없다면)
        # 실제 로또 회차에 맞춰야 함.
        # 가장 현실적인 방법: JSON 파일의 데이터 개수만큼 역순으로 회차를 부여하고,
        # 최신 회차는 API 업데이트 기능을 통해 추가.
        
        # 현재는 JSON 데이터의 첫 번째 데이터를 가장 오래된 회차, 마지막 데이터를 가장 최신 회차로 간주합니다.
        # 따라서, 시작 회차를 JSON 데이터의 길이만큼 빼서 조정합니다.
        start_round_for_json = (current_max_round if current_max_round > 0 else 1179) - len(past_rank1_data) + 1 # 1179는 예시, 실제 최신 회차를 반영해야 합니다.

        uploaded_count = 0
        skipped_count = 0
        batch = db.batch() # Firestore Batch Write를 사용하여 여러 문서 한 번에 쓰기

        # JSON 파일의 데이터를 순회하며 Firestore에 저장
        for i, combo in enumerate(past_rank1_data):
            round_num_to_save = start_round_for_json + i

            doc_ref = db.collection('winning_numbers_rank1').document(str(round_num_to_save))

            # 해당 회차가 이미 존재하면 스킵 (추후에 덮어쓰기 기능이 필요할 수도 있음)
            # 여기서는 get() 호출을 피하여 배치 쓰기 효율을 높입니다.
            # 만약 이미 존재하는 문서라면 set()이 덮어쓰므로 문제가 되지 않습니다.
            # 중복 스킵 로직을 원하면 doc_ref.get().exists를 먼저 확인해야 합니다.
            # (그러나 배치 내에서는 get() 호출은 추천되지 않음)
            
            # 보너스 번호는 JSON 파일에 없으므로 0으로 설정
            batch.set(doc_ref, {
                'round': round_num_to_save,
                'numbers': sorted(combo),
                'bonus': 0, # 과거 데이터에 보너스 번호가 없으므로 0으로 설정하거나 별도 처리 필요
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            uploaded_count += 1
            if uploaded_count % 400 == 0: # 400개마다 배치 커밋 (Firestore Batch 제한은 500이므로 400개 권장)
                batch.commit()
                batch = db.batch() # 새 배치 시작

        if uploaded_count % 400 != 0: # 남은 문서 커밋
            batch.commit()

        # 데이터 업로드 후 ALL_WINNING 및 rank1, rank2, rank3 전역 변수 새로고침
        load_winning_data_from_firestore()

        return jsonify({"status": "success", "message": f"과거 1등 번호 {uploaded_count}개 업로드 완료!", "total_loaded_rank1": len(rank1)}), 200

    except Exception as e:
        print(f"과거 1등 번호 업로드 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": f"과거 1등 번호 업로드 오류: {e}"}), 500
# --- END: NEW Admin Route for Past Rank1 Upload ---


# --- START: NEW Admin Route for Past Rank2/3 Upload ---
@app.route('/admin_upload_past_rank2_3', methods=['POST'])
def admin_upload_past_rank2_3():
    pw = request.form.get("pw")
    if pw != "1234":
        return jsonify({"status": "error", "message": "관리자 비밀번호가 틀렸습니다."}), 403

    if db is None:
        return jsonify({"status": "error", "message": "Firestore DB가 초기화되지 않았습니다."}), 500

    try:
        # 2등 데이터 업로드
        # 파일 경로를 static 폴더 내부로 수정
        past_rank2_data = load_rank_data_from_json('static/winning_numbers_rank2.json', 'rank2') # <--- 이 부분 수정
        uploaded_rank2_count = 0
        if past_rank2_data:
            batch2 = db.batch()
            for combo in past_rank2_data:
                combo_id = "_".join(map(str, sorted(combo)))
                doc_ref = db.collection('winning_numbers_rank2').document(combo_id)
                # 문서 존재 여부 확인을 배치 내에서는 하지 않음 (덮어쓰기 됨)
                batch2.set(doc_ref, {
                    'combination': sorted(combo),
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
                uploaded_rank2_count += 1
                if uploaded_rank2_count % 400 == 0: # 400개마다 커밋
                    batch2.commit()
                    batch2 = db.batch()
            if uploaded_rank2_count % 400 != 0: # 남은 문서 커밋
                batch2.commit()

        # 3등 데이터 업로드
        # 파일 경로를 static 폴더 내부로 수정
        past_rank3_data = load_rank_data_from_json('static/winning_numbers_rank3.json', 'rank3') # <--- 이 부분 수정
        uploaded_rank3_count = 0
        if past_rank3_data:
            batch3 = db.batch()
            for combo in past_rank3_data:
                combo_id = "_".join(map(str, sorted(combo)))
                doc_ref = db.collection('winning_numbers_rank3').document(combo_id)
                # 문서 존재 여부 확인을 배치 내에서는 하지 않음 (덮어쓰기 됨)
                batch3.set(doc_ref, {
                    'combination': sorted(combo),
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
                uploaded_rank3_count += 1
                if uploaded_rank3_count % 400 == 0: # 400개마다 커밋
                    batch3.commit()
                    batch3 = db.batch()
            if uploaded_rank3_count % 400 != 0: # 남은 문서 커밋
                batch3.commit()

        # 데이터 업로드 후 ALL_WINNING 및 rank1, rank2, rank3 전역 변수 새로고침
        load_winning_data_from_firestore()

        return jsonify({
            "status": "success",
            "message": f"과거 2등 조합 {uploaded_rank2_count}개, 3등 조합 {uploaded_rank3_count}개 업로드 완료!",
            "total_loaded_rank2": len(ALL_WINNING.get("2", set())),
            "total_loaded_rank3": len(ALL_WINNING.get("3", set()))
        }), 200

    except Exception as e:
        print(f"과거 2/3등 번호 업로드 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": f"과거 2/3등 번호 업로드 오류: {e}"}), 500
# --- END: NEW Admin Route for Past Rank2/3 Upload ---


# Route for ads.txt (for ad services)
@app.route('/ads.txt')
def ads_txt():
    # Render.com에서 static files를 제공하는 방식에 따라 경로를 조정해야 할 수 있습니다.
    # 일반적으로는 static 폴더에 ads.txt를 두고 send_from_directory를 사용합니다.
    # 여기서는 간단하게 텍스트를 직접 반환합니다.
    return Response("google.com, pub-2748658493247983, DIRECT, f08c47fec0942fa0", mimetype='text/plain')

# Route for sitemap.xml
@app.route('/sitemap.xml')
def sitemap_xml():
    # 동적으로 사이트맵을 생성합니다.
    # 실제 URL은 Render.com에 배포된 도메인을 사용해야 합니다.
    base_url = "https://smartpick.wow-daddy.com" # 실제 도메인으로 변경하세요!

    # 웹사이트의 모든 주요 페이지 URL을 리스트로 정의
    urls = [
        {"loc": f"{base_url}/", "lastmod": datetime.date.today().isoformat(), "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base_url}/filter", "lastmod": datetime.date.today().isoformat(), "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base_url}/hotpick", "lastmod": datetime.date.today().isoformat(), "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base_url}/stats", "lastmod": datetime.date.today().isoformat(), "changefreq": "daily", "priority": "0.7"},
        {"loc": f"{base_url}/lotto-dna-test", "lastmod": datetime.date.today().isoformat(), "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base_url}/about", "lastmod": datetime.date.today().isoformat(), "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base_url}/privacy", "lastmod": datetime.date.today().isoformat(), "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base_url}/disclaimer", "lastmod": datetime.date.today().isoformat(), "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base_url}/contact", "lastmod": datetime.date.today().isoformat(), "changefreq": "monthly", "priority": "0.5"},
    ]

    sitemap_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url_data in urls:
        sitemap_content += '  <url>\n'
        sitemap_content += f'    <loc>{url_data["loc"]}</loc>\n'
        sitemap_content += f'    <lastmod>{url_data["lastmod"]}</lastmod>\n'
        sitemap_content += f'    <changefreq>{url_data["changefreq"]}</changefreq>\n'
        sitemap_content += f'    <priority>{url_data["priority"]}</priority>\n'
        sitemap_content += '  </url>\n'
    sitemap_content += '</urlset>'

    return Response(sitemap_content, mimetype='application/xml')


# Health check endpoint for deployment environments
@app.route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return "OK", 200

# New Route for Lotto DNA Test page
@app.route('/lotto-dna-test')
def lotto_dna_test_page():
    # 클라이언트에서 로그를 직접 보낼 것이므로 여기서는 log_event 호출하지 않음
    current_year = datetime.datetime.now().year
    return render_template('lotto_type_test.html', kakao_js_key=KAKAO_JAVASCRIPT_KEY, now={'year': current_year})

# New API endpoint to generate Lotto DNA numbers
@app.route('/generate_dna_lotto_numbers', methods=['POST'])
def generate_dna_lotto_numbers():
    try:
        # 클라이언트에서 넘어온 DNA 유형 (현재는 사용하지 않고 무작위 생성)
        # dna_type = request.json.get('dna_type')

        # 무작위 로또 번호 6개 생성 (1부터 45까지, 중복 없이)
        generated_numbers = random.sample(range(1, 46), 6)

        return jsonify({"numbers": generated_numbers}), 200
    except Exception as e:
        print(f"로또 DNA 번호 생성 오류: {e}")
        return jsonify({"error": "번호 생성 중 오류가 발생했습니다."}), 500

# New Route for the Fun Lotto Test Hub page
@app.route('/fun-lotto-test')
def fun_lotto_test_hub():
    return render_template('fun_lotto_test_hub.html', now=datetime.datetime.now()) # <--- 추가

# --- START OF NEW MBTI LOTTO FORTUNE FEATURE ---

# MBTI 유형별 로또 운세 데이터 (mbti_lotto_fortune.html에서 추출)
MBTI_FORTUNE_DATA = {
    "ISTP": {
        "title": "ISTP 로또 운세: 뚝심 있는 탐험가",
        "description": "ISTP는 독립적이고 문제 해결 능력이 뛰어납니다. 로또에서도 자신만의 방식으로 번호를 분석하고 선택하는 경향이 있습니다. 즉흥적으로 끌리는 번호보다는, 패턴이나 논리적인 근거를 찾아 뚝심 있게 밀고 나가는 것이 행운을 불러올 수 있습니다.",
        "luckyTip": "이번 주 ISTP의 행운 번호는 **최근 10주간 당첨 이력이 없지만, 꾸준히 선택되는 경향이 있는 번호**들입니다. 기존의 틀을 깨는 번호에서 기회가 숨어있을 수 있습니다!"
    },
    "ISFP": {
        "title": "ISFP 로또 운세: 유연한 예술가",
        "description": "ISFP는 감성적이고 유연하며, 주변의 아름다움에 민감합니다. 로또 번호를 선택할 때도 직관이나 느낌에 따라 자유롭게 선택하는 경향이 있습니다. 복잡한 분석보다는, 그날의 기분이나 꿈, 혹은 주변에서 영감을 받은 번호들이 의외의 행운을 가져다줄 수 있습니다.",
        "luckyTip": "이번 주 ISFP의 행운 번호는 **당신이 최근에 인상 깊게 본 숫자, 혹은 주변 환경에서 문득 떠오른 번호**들입니다. 직관을 믿고 선택해 보세요!"
    },
    "ESTP": {
        "title": "ESTP 로또 운세: 대담한 행동가",
        "description": "ESTP는 에너지 넘치고 현실적이며, 즉각적인 행동을 선호합니다. 로또 번호를 고를 때도 과감하고 스릴 있는 선택을 즐길 수 있습니다. 빠르게 결정을 내리고, 새로운 시도를 두려워하지 않는 대담함이 의외의 당첨으로 이어질 수 있습니다.",
        "luckyTip": "이번 주 ESTP의 행운 번호는 **가장 최근에 당첨된 번호들 중 당신의 눈길을 끈 숫자들과 이웃하는 번호들**입니다. 과감한 시도가 행운을 만듭니다!"
    },
    "ESFP": {
        "title": "ESFP 로또 운세: 열정적인 연예인",
        "description": "ESFP는 사교적이고 활기차며, 즐거움을 추구합니다. 로또를 고를 때도 재미와 유희를 중요하게 생각할 것입니다. 혼자만의 고민보다는 친구들과 함께 번호를 고르거나, 흥미로운 스토리를 가진 번호를 선택하는 것이 즐거운 경험과 함께 뜻밖의 행운을 가져올 수 있습니다.",
        "luckyTip": "이번 주 ESFP의 행운 번호는 **친구들과의 모임에서 나온 숫자, 혹은 당신이 가장 좋아하는 숫자**들을 조합한 것입니다. 즐거운 에너지가 행운을 이니다!"
    },
    "ISTJ": {
        "title": "ISTJ 로또 운세: 원칙주의자",
        "description": "ISTJ는 책임감 있고 논리적이며, 계획에 따라 행동합니다. 로또 번호를 선택할 때도 철저한 분석과 규칙을 선호할 수 있습니다. 과거 데이터, 통계, 출현 빈도 등을 꼼꼼히 따져서 신뢰성 있는 번호를 선택하는 것이 좋습니다.",
        "luckyTip": "이번 주 ISTJ의 행운 번호는 **과거 당첨 번호 데이터에서 1등 번호로는 출현하지 않았지만, 2등/3등 번호로 자주 조합되었던 숫자**들입니다. 원칙에 충실한 선택이 중요합니다!"
    },
    "ISFJ": {
        "title": "ISFJ 로또 운세: 헌신적인 수호자",
        "description": "ISFJ는 따뜻하고 성실하며, 안정과 조화를 중요하게 생각합니다. 로또 번호를 선택할 때도 익숙하고 안정적인 번호들을 선호할 수 있습니다. 의미 있는 날짜나, 오랫동안 꾸준히 선택해온 번호들에서 안정적인 행운을 기대해 볼 수 있습니다.",
        "luckyTip": "이번 주 ISFJ의 행운 번호는 **당신에게 의미 있는 기념일 숫자, 혹은 당신이 오랫동안 꾸준히 사랑해온 번호**들입니다. 익숙함 속에서 행운이 찾아옵니다!"
    },
    "ESTJ": {
        "title": "ESTJ 로또 운세: 경영자",
        "description": "ESTJ는 현실적이고 조직적이며, 리더십이 강합니다. 로또 번호를 선택할 때도 효율적이고 체계적인 접근을 할 것입니다. 전략적인 분석과 함께, 단호하게 결정을 내리는 실행력이 행운을 만들어낼 수 있습니다.",
        "luckyTip": "이번 주 ESTJ의 행운 번호는 **과거 50회차 당첨 번호 중 가장 높은 출현 빈도를 보인 번호**들과 그 주변 번호들을 조합한 것입니다. 분석적인 선택이 당신을 리드합니다!"
    },
    "ESFJ": {
        "title": "ESFJ 로또 운세: 사교적인 외교관",
        "description": "ESFJ는 친화적이고 배려심이 깊으며, 조화로운 관계를 중요하게 생각합니다. 로또 번호를 고를 때도 주변 사람들과의 소통을 통해 영감을 얻거나, 함께 번호를 공유하는 즐거움을 느낄 수 있습니다. 좋은 사람들과 함께하는 시간 속에서 행운의 번호가 나올 수 있습니다.",
        "luckyTip": "이번 주 ESFJ의 행운 번호는 **친구나 가족과의 대화에서 우연히 나온 숫자, 또는 다수가 좋아하는 숫자**들을 조합한 것입니다. 함께하는 즐거움이 행운을 키웁니다!"
    },
    "INFJ": {
        "title": "INFJ 로또 운세: 통찰력 있는 예언가",
        "description": "INFJ는 직관적이고 통찰력이 깊으며, 이상을 추구합니다. 로또 번호를 선택할 때도 남들이 보지 못하는 의미나 패턴을 발견하려 할 수 있습니다. 꿈에서 본 숫자나 강하게 끌리는 직관적인 번호들이 큰 행운을 가져다줄 수 있습니다.",
        "luckyTip": "이번 주 INFJ의 행운 번호는 **당신의 내면에서 강하게 끌리는 숫자들, 혹은 의미심장한 패턴이 보이는 번호**들입니다. 당신의 직관을 믿어보세요!"
    },
    "INFP": {
        "title": "INFP 로또 운세: 이상주의자",
        "description": "INFP는 창의적이고 이상적이며, 가치를 중요하게 생각합니다. 로또 번호를 고를 때도 개인적인 의미나 스토리가 있는 번호들을 선호할 것입니다. 세상에 긍정적인 영향을 줄 수 있는 번호나, 자신만의 특별한 의미가 담긴 번호가 행운을 부를 수 있습니다.",
        "luckyTip": "이번 주 INFP의 행운 번호는 **당신의 삶의 중요한 가치와 연결된 숫자, 혹은 당신이 가장 아끼는 소설이나 영화 속 번호**들입니다. 의미 있는 선택이 행운을 만듭니다!"
    },
    "ENFJ": {
        "title": "ENFJ 로또 운세: 정의로운 옹호자",
        "description": "ENFJ는 열정적이고 타인에게 영감을 주며, 사회적 정의를 추구합니다. 로또 번호를 선택할 때도 다른 사람들에게 좋은 영향을 줄 수 있는 번호나, 긍정적인 의미를 담은 번호를 선호할 수 있습니다. 당신의 선한 영향력이 로또 행운으로 이어질 수 있습니다.",
        "luckyTip": "이번 주 ENFJ의 행운 번호는 **당신이 존경하는 인물의 생일이나 의미 있는 날짜, 혹은 사회적 이슈와 관련된 숫자**들입니다. 긍정적인 에너지가 행운을 이끕니다!"
    },
    "ENFP": {
        "title": "ENFP 로또 운세: 자유로운 활동가",
        "description": "ENFP는 창의적이고 열정적이며, 새로운 가능성을 탐구합니다. 로또 번호를 고를 때도 틀에 얽매이지 않고 자유롭게, 그리고 다양한 방식으로 시도하는 것을 즐길 것입니다. 예상치 못한 조합이나, 즉흥적인 아이디어가 뜻밖의 행운을 가져올 수 있습니다.",
        "luckyTip": "이번 주 ENFP의 행운 번호는 **최근 당첨 번호에 포함되지 않았던 숫자들 중 당신의 직관에 가장 강하게 와닿는 번호**들입니다. 틀을 깨는 시도가 행운을 부릅니다!"
    },
    "INTJ": {
        "title": "INTJ 로또 운세: 전략가",
        "description": "INTJ는 분석적이고 전략적이며, 장기적인 계획을 선호합니다. 로또 번호를 선택할 때도 고도로 계산된 전략과 논리적인 접근을 할 것입니다. 복잡한 통계 분석이나 자신만의 예측 모델을 통해 가장 확률 높은 번호를 찾아낼 수 있습니다.",
        "luckyTip": "이번 주 INTJ의 행운 번호는 **각 번호대의 출현 빈도와 홀짝 비율, 고저 비율을 고려하여 통계적으로 가장 균형 잡힌 조합**입니다. 당신의 전략이 승리합니다!"
    },
    "INTP": {
        "title": "INTP 로또 운세: 논리적인 사색가",
        "description": "INTP는 지적이고 분석적이며, 복잡한 문제 해결을 즐깁니다. 로또 번호를 고를 때도 심층적인 분석과 이론적인 접근을 할 것입니다. 자신만의 독특한 패턴이나 논리를 적용하여 번호를 선택하는 것이 의외의 결과를 가져올 수 있습니다.",
        "luckyTip": "이번 주 INTP의 행운 번호는 **수학적 패턴(예: 피보나치 수열)이나 특정 알고리즘을 적용하여 도출된 번호**들입니다. 논리적인 탐구가 행운을 발견합니다!"
    },
    "ENTJ": {
        "title": "ENTJ 로또 운세: 통솔자",
        "description": "ENTJ는 단호하고 비전을 제시하며, 목표 달성을 위해 강력하게 추진합니다. 로또 번호를 선택할 때도 명확한 목표를 세우고, 이를 달성하기 위한 효율적인 방법을 모색할 것입니다. 자신감 있는 선택과 강력한 추진력이 로또 행운을 끌어당길 수 있습니다.",
        "luckyTip": "이번 주 ENTJ의 행운 번호는 **가장 최근의 당첨 번호들을 기반으로 미래 추이를 예측하여 선정한 번호**들입니다. 당신의 결단력이 행운을 지휘합니다!"
    },
    "ENTP": {
        "title": "ENTP 로또 운세: 발명가",
        "description": "ENTP는 혁신적이고 독창적이며, 새로운 아이디어에 열려 있습니다. 로또 번호를 고를 때도 기발하고 독특한 방식으로 접근하는 것을 즐길 것입니다. 고정관념을 깨는 예측 불가능한 시도가 의외의 큰 행운을 불러올 수 있습니다.",
        "luckyTip": "이번 주 ENTP의 행운 번호는 **일반적인 로또 번호 패턴을 벗어나, 당신의 기발한 아이디어로 조합된 번호**들입니다. 창의적인 발상이 행운을 발명합니다!"
    }
}

def generate_mbti_lotto_numbers(mbti_type):
    """
    MBTI 유형에 따라 로또 번호를 생성하는 함수.
    기존 generate_numbers 함수를 활용하여 필터 조건을 조절합니다.
    """
    numbers = []

    # MBTI 유형에 따른 번호 생성 전략
    if mbti_type in ["ISTJ", "ISFJ", "ESTJ", "ESFJ"]: # 현실적, 전통적, 안정성 중시
        # 과거 당첨 이력이 없는 번호 위주, 또는 특정 통계 기반
        # 여기서는 1, 2, 3등 조합을 제외하고, 최근 5주간 인기 번호 제외
        numbers = generate_numbers(
            exclude_ranks=['1', '2', '3'],
            exclude_hot_n=5,
            count=1
        )[0] # 첫 번째 결과만 가져옴
    elif mbti_type in ["ISTP", "ISFP", "ESTP", "ESFP"]: # 즉흥적, 탐험적, 경험 중시
        # 무작위 번호 생성, 특정 패턴 배제
        # 여기서는 1등만 제외하고, 연번은 2개까지만 허용
        numbers = generate_numbers(
            exclude_ranks=['1'],
            exclude_consecutive=2,
            count=1
        )[0]
    elif mbti_type in ["INFJ", "INFP", "ENFJ", "ENFP"]: # 직관적, 이상적, 창의적
        # 완전 무작위 또는 특정 직관적인 번호 포함 (여기서는 순수 무작위)
        numbers = random.sample(range(1, 46), 6)
    elif mbti_type in ["INTJ", "INTP", "ENTJ", "ENTP"]: # 분석적, 전략적, 논리적
        # 전략적 필터 적용 (예: 1,2,3등 제외 + 특정 고빈도/저빈도 번호 활용)
        # 여기서는 1, 2, 3등 조합 제외
        numbers = generate_numbers(
            exclude_ranks=['1', '2', '3'],
            count=1
        )[0]
    else: # 기본값 또는 알 수 없는 MBTI 유형
        numbers = random.sample(range(1, 46), 6) # 완전 무작위

    return sorted(numbers)

# MBTI 유형에 따른 로또 운세 및 번호 생성 API 엔드포인트
@app.route('/get_mbti_lotto_fortune', methods=['POST'])
def get_mbti_lotto_fortune():
    try:
        data = request.json
        mbti_type = data.get('mbti_type', 'UNKNOWN').upper()

        if mbti_type not in MBTI_FORTUNE_DATA:
            mbti_type = 'UNKNOWN' # 유효하지 않은 MBTI는 기본값 처리 (혹은 오류 반환)
            # UNKNOWN MBTI에 대한 기본 데이터를 MBTI_FORTUNE_DATA에 추가해야 합니다.
            # 지금은 에러 방지를 위해 간단히 무작위 번호로 처리.
            # 실제 서비스에서는 에러 처리 또는 기본 MBTI 운세를 보여주는 것이 좋습니다.

        # MBTI_FORTUNE_DATA에서 해당 MBTI의 정보 가져오기
        fortune_info = MBTI_FORTUNE_DATA.get(mbti_type, {
            "title": "알 수 없는 MBTI 로또 운세",
            "description": "선택하신 MBTI 유형에 대한 정보가 없습니다. 일반적인 로또 운세를 확인해 보세요.",
            "luckyTip": "당신의 행운을 빕니다!"
        })

        # MBTI 유형에 따른 로또 번호 생성
        generated_numbers = generate_mbti_lotto_numbers(mbti_type)

        # Firestore에 로그 기록 (MBTI 추천 이벤트)
        if db:
            try:
                user_id = f"{app_id}_user_{random.getrandbits(64)}"
                log_data = {
                    "dt": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "event": "mbti_recommend",
                    "detail": {
                        "mbti_type": mbti_type,
                        "recommended_numbers": generated_numbers
                    },
                    "userId": user_id
                }
                db.collection('artifacts').document(app_id).collection('users').document(user_id).collection('logs').add(log_data)
                print(f"MBTI 추천 로그 기록 완료: {mbti_type} - {generated_numbers}")

                # 전체 추천 건수 업데이트 (선택 사항, 필요 시 추가)
                stats_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('app_stats').document('recommendation_counts')
                stats_doc_ref.update({
                    'total_recommendations': firestore.Increment(1),
                    'last_updated': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"MBTI 추천 로그 또는 통계 업데이트 오류: {e}")

        return jsonify({
            "mbti_type": mbti_type,
            "title": fortune_info["title"],
            "description": fortune_info["description"],
            "luckyTip": fortune_info["luckyTip"],
            "numbers": generated_numbers
        }), 200

    except Exception as e:
        print(f"MBTI 로또 운세 생성 오류: {e}")
        return jsonify({"error": "MBTI 로또 운세 생성 중 오류가 발생했습니다."}), 500

# --- END OF NEW MBTI LOTTO FORTUNE FEATURE ---

# --- START OF NEW MBTI LOTTO FORTUNE FEATURE ROUTES ---
@app.route('/mbti-lotto-test')
def mbti_lotto_test_page():
    """
    사용자에게 MBTI를 선택하도록 하는 입력 페이지를 렌더링합니다.
    이 페이지는 MBTI별 로또 운세 결과를 보여주는 mbti_lotto_fortune.html과는 별개의 입력 페이지입니다.
    """
    # 현재 연도를 Jinja2 템플릿에 전달하여 푸터 등에 활용할 수 있도록 합니다.
    current_year = datetime.datetime.now().year
    return render_template('mbti_lotto_test_input.html', kakao_js_key=KAKAO_JAVASCRIPT_KEY, now={'year': current_year})



# MBTI 로또 운세 결과를 표시하는 페이지 (API 응답을 받은 후 프론트엔드에서 리다이렉트 또는 동적 표시)
@app.route('/mbti-lotto-fortune')
def mbti_lotto_fortune_result_page():
    mbti_type = request.args.get('mbti')
    numbers_str = request.args.get('numbers') # 콤마로 구분된 문자열
    title = request.args.get('title')
    description = request.args.get('description')
    lucky_tip = request.args.get('luckyTip')

    numbers = []
    if numbers_str:
        try:
            numbers = [int(n) for n in numbers_str.split(',') if n.strip().isdigit()]
        except ValueError:
            print(f"Invalid numbers string received: {numbers_str}")
            numbers = [] # 유효하지 않으면 빈 리스트

    # 날짜 정보 (푸터 등 Jinja2 템플릿에 필요할 수 있음)
    current_date = datetime.datetime.now()

    # 필요한 데이터를 Jinja2 템플릿으로 전달
    return render_template(
        'mbti_lotto_fortune.html',
        mbti_type=mbti_type,
        title=title,
        description=description,
        luckyTip=lucky_tip,
        numbers=numbers,
        kakao_js_key=KAKAO_JAVASCRIPT_KEY,
        now={'year': current_date.year} # 현재 연도만 필요하다면
    )
# --- END OF NEW MBTI LOTTO FORTUNE FEATURE ROUTES ---

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=os.environ.get('PORT', 5000))
